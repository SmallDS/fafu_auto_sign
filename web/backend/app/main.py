"""FastAPI application and Web API routes."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, AsyncIterator, Literal

from fastapi import Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.amap_proxy import (
    AmapProxyError,
    AmapResponseTooLarge,
    AmapUpstreamUnavailable,
    UnsupportedAmapPath,
    install_amap_access_log_filter,
    proxy_amap_request,
)
from app.database import SessionLocal, get_db, run_migrations
from app.errors import ConfigurationIncomplete, api_error
from app.image_store import MAX_UPLOAD_FILES, InvalidImage, store_upload
from app.legacy import import_legacy_config
from app.log_reader import read_logs
from app.manual_sign import (
    ExecutionBusy,
    ManualSignService,
    TaskDetailsUnavailable,
    TaskNoLongerActive,
    UpstreamUnavailable,
)
from app.models import Image, RunHistory
from app.paths import FRONTEND_DIST, LOG_DIR, ensure_data_directories
from app.repository import (
    configuration_state,
    get_or_create_settings,
    image_path,
    image_to_read,
    latest_run,
    run_to_read,
    settings_to_read,
    seven_day_stats,
    update_settings,
)
from app.schemas import (
    HealthResponse,
    ImagePage,
    ImageRead,
    LogPage,
    MapConfigRead,
    RunPage,
    RunRead,
    SettingsRead,
    SettingsUpdate,
    SignTaskDetailsRead,
    SignTaskPage,
    SignTaskRead,
    SignTaskSubmit,
    StatusResponse,
    WorkerActionResponse,
)
from app.worker import WorkerManager
from fafu_auto_sign.logging_config import setup_logging
from fafu_auto_sign.services.notification_service import NotificationService

logger = logging.getLogger(__name__)
worker = WorkerManager()
manual_sign = ManualSignService(worker)
DbSession = Annotated[Session, Depends(get_db)]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    ensure_data_directories()
    run_migrations()
    with SessionLocal() as session:
        get_or_create_settings(session)
        import_legacy_config(session)
        settings = get_or_create_settings(session)
        log_level = settings.log_level
    setup_logging(log_level, log_dir=str(LOG_DIR))
    install_amap_access_log_filter()
    worker.start()
    try:
        yield
    finally:
        worker.stop()


app = FastAPI(title="FAFU Auto Sign Web", version="1.0.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    fields: dict[str, str] = {}
    for error in exc.errors():
        location = error.get("loc", ())
        key = str(location[-1]) if location else "request"
        fields[key] = str(error.get("msg", "输入无效"))
    return JSONResponse(
        status_code=422,
        content={
            "detail": {"code": "VALIDATION_ERROR", "message": "请求参数校验失败", "fields": fields}
        },
    )


@app.get("/api/health", response_model=HealthResponse)
def health(session: DbSession) -> HealthResponse:
    session.execute(text("SELECT 1"))
    settings = get_or_create_settings(session)
    configured, _ = configuration_state(session, settings)
    return HealthResponse(worker_state=worker.snapshot()["state"], configured=configured)


@app.get("/api/settings", response_model=SettingsRead)
def get_settings(session: DbSession) -> SettingsRead:
    return settings_to_read(session, get_or_create_settings(session))


@app.put("/api/settings", response_model=SettingsRead)
def put_settings(payload: SettingsUpdate, session: DbSession) -> SettingsRead:
    try:
        settings = update_settings(session, payload)
    except ValueError as exc:
        session.rollback()
        raise api_error(422, "VALIDATION_ERROR", "配置校验失败", {"settings": str(exc)}) from exc
    worker.notify_configuration_changed()
    return settings_to_read(session, settings)


@app.get("/api/map/config", response_model=MapConfigRead)
def map_config(session: DbSession) -> MapConfigRead:
    settings = get_or_create_settings(session)
    enabled = bool(
        settings.amap_enabled
        and settings.amap_js_key
        and settings.amap_security_js_code
    )
    return MapConfigRead(
        enabled=enabled,
        js_key=settings.amap_js_key if enabled else None,
        jitter=settings.jitter,
    )


@app.get("/_AMapService/{service_path:path}", response_model=None)
def amap_service_proxy(
    service_path: str,
    request: Request,
    session: DbSession,
) -> Response:
    settings = get_or_create_settings(session)
    if not (
        settings.amap_enabled
        and settings.amap_js_key
        and settings.amap_security_js_code
    ):
        raise api_error(409, "AMAP_NOT_CONFIGURED", "高德地图尚未启用或配置不完整")
    try:
        return proxy_amap_request(
            service_path,
            request.query_params.multi_items(),
            settings.amap_security_js_code,
        )
    except UnsupportedAmapPath as exc:
        raise api_error(404, "AMAP_PATH_NOT_ALLOWED", "不支持的高德服务路径") from exc
    except AmapResponseTooLarge as exc:
        raise api_error(502, "AMAP_RESPONSE_TOO_LARGE", "高德服务响应过大") from exc
    except AmapUpstreamUnavailable as exc:
        raise api_error(502, "AMAP_UPSTREAM_ERROR", "无法连接高德地图服务") from exc
    except AmapProxyError as exc:
        raise api_error(502, "AMAP_PROXY_ERROR", "高德地图代理请求失败") from exc


@app.get("/api/status", response_model=StatusResponse)
def status(session: DbSession) -> StatusResponse:
    settings = get_or_create_settings(session)
    configured, missing = configuration_state(session, settings)
    snapshot = worker.snapshot()
    latest = latest_run(session)
    return StatusResponse(
        configured=configured,
        worker_state=snapshot["state"],
        last_check_at=snapshot["last_check_at"],
        next_check_at=snapshot["next_check_at"],
        last_error=latest.error if latest else None,
        recent_run=run_to_read(latest) if latest else None,
        stats_7d=seven_day_stats(session),
    )


@app.post("/api/worker/pause", response_model=WorkerActionResponse)
def pause_worker(session: DbSession) -> WorkerActionResponse:
    settings = get_or_create_settings(session)
    settings.worker_enabled = False
    settings.config_version += 1
    session.commit()
    worker.notify_configuration_changed()
    state = worker.snapshot()["state"]
    return WorkerActionResponse(state=state, message="当前任务结束后将暂停自动检查")


@app.post("/api/worker/resume", response_model=WorkerActionResponse)
def resume_worker(session: DbSession) -> WorkerActionResponse:
    settings = get_or_create_settings(session)
    configured, missing = configuration_state(session, settings)
    if not configured:
        raise api_error(
            409, "CONFIGURATION_INCOMPLETE", "配置不完整，无法恢复", {"missing": ",".join(missing)}
        )
    settings.worker_enabled = True
    settings.config_version += 1
    session.commit()
    worker.notify_configuration_changed()
    return WorkerActionResponse(state="idle", message="已恢复自动检查")


@app.post("/api/worker/run-now", response_model=WorkerActionResponse)
def run_now(session: DbSession) -> WorkerActionResponse:
    configured, missing = configuration_state(session)
    if not configured:
        raise api_error(
            409, "CONFIGURATION_INCOMPLETE", "配置不完整，无法执行", {"missing": ",".join(missing)}
        )
    if not worker.request_run_now():
        raise api_error(409, "WORKER_BUSY", "已有签到任务正在执行")
    return WorkerActionResponse(state="executing", message="已提交立即检查")


@app.get("/api/sign-tasks", response_model=SignTaskPage)
def list_sign_tasks(
    session: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> SignTaskPage:
    try:
        result = manual_sign.list_tasks(session, page, page_size)
    except ConfigurationIncomplete as exc:
        raise api_error(409, "CONFIGURATION_INCOMPLETE", "请先配置 Token") from exc
    except ExecutionBusy as exc:
        raise api_error(409, "WORKER_BUSY", "已有 FAFU 操作正在执行") from exc
    except UpstreamUnavailable as exc:
        raise api_error(502, "FAFU_UPSTREAM_ERROR", "无法读取 FAFU 签到任务") from exc
    return SignTaskPage(
        items=[
            SignTaskRead(
                id=item.id,
                name=item.name,
                begin_time=item.begin_time,
                end_time=item.end_time,
            )
            for item in result.items
        ],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        has_more=result.has_more,
    )


@app.get("/api/sign-tasks/{task_id}", response_model=SignTaskDetailsRead)
def get_sign_task_details(task_id: int, session: DbSession) -> SignTaskDetailsRead:
    try:
        details = manual_sign.get_details(session, task_id)
    except ConfigurationIncomplete as exc:
        raise api_error(409, "CONFIGURATION_INCOMPLETE", "请先配置 Token") from exc
    except TaskDetailsUnavailable as exc:
        raise api_error(404, "TASK_DETAILS_UNAVAILABLE", "任务详情不可用") from exc
    except ExecutionBusy as exc:
        raise api_error(409, "WORKER_BUSY", "已有 FAFU 操作正在执行") from exc
    except UpstreamUnavailable as exc:
        raise api_error(502, "FAFU_UPSTREAM_ERROR", "无法读取 FAFU 任务详情") from exc
    return SignTaskDetailsRead(
        task_id=details.task_id,
        position_id=details.position_id,
        base_lng=details.base_lng,
        base_lat=details.base_lat,
        position_name=details.position_name,
    )


@app.post("/api/sign-tasks/{task_id}/submit", response_model=RunRead)
def submit_sign_task(
    task_id: int,
    payload: SignTaskSubmit,
    session: DbSession,
) -> RunRead:
    try:
        row = manual_sign.submit(
            session,
            task_id=task_id,
            source_page=payload.source_page,
            page_size=payload.page_size,
        )
    except ConfigurationIncomplete as exc:
        raise api_error(409, "CONFIGURATION_INCOMPLETE", "完整签到配置尚未就绪") from exc
    except ExecutionBusy as exc:
        raise api_error(409, "WORKER_BUSY", "已有签到任务正在执行") from exc
    except TaskNoLongerActive as exc:
        raise api_error(
            409,
            "TASK_NO_LONGER_ACTIVE",
            "任务已失效或不在签到时间内",
            {"run_id": str(exc.run_id)},
        ) from exc
    except UpstreamUnavailable as exc:
        fields = {"run_id": str(exc.run_id)} if exc.run_id is not None else None
        raise api_error(502, "FAFU_UPSTREAM_ERROR", "FAFU 签到请求失败", fields) from exc
    return run_to_read(row)


@app.get("/api/images", response_model=ImagePage)
def list_images(
    session: DbSession,
    category: Literal["library", "latest"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ImagePage:
    count_query = select(func.count(Image.id))
    images_query = select(Image)
    if category:
        count_query = count_query.where(Image.purpose == category)
        images_query = images_query.where(Image.purpose == category)
    total = session.scalar(count_query) or 0
    rows = session.scalars(
        images_query.order_by(Image.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ImagePage(
        items=[image_to_read(row) for row in rows], total=total, page=page, page_size=page_size
    )


@app.post("/api/images", response_model=list[ImageRead], status_code=201)
async def upload_images(
    session: DbSession,
    files: Annotated[list[UploadFile], File(...)],
    category: Annotated[Literal["library", "latest"], Form()] = "library",
) -> list[ImageRead]:
    if len(files) > MAX_UPLOAD_FILES:
        raise api_error(413, "TOO_MANY_FILES", "每次最多上传 10 张图片")
    created: list[Image] = []
    try:
        for upload in files:
            created.append(await store_upload(session, upload, category, commit=False))
        session.commit()
    except InvalidImage as exc:
        session.rollback()
        for image in created:
            image_path(image).unlink(missing_ok=True)
        raise api_error(422, "INVALID_IMAGE", str(exc)) from exc
    except Exception:
        session.rollback()
        for image in created:
            image_path(image).unlink(missing_ok=True)
        raise
    worker.notify_configuration_changed()
    return [image_to_read(row) for row in created]


@app.get("/api/images/{image_id}", response_class=FileResponse)
def get_image(image_id: str, session: DbSession) -> FileResponse:
    image = session.get(Image, image_id)
    if image is None:
        raise api_error(404, "IMAGE_NOT_FOUND", "图片不存在")
    path = image_path(image)
    if not path.is_file():
        raise api_error(404, "IMAGE_FILE_MISSING", "图片文件不存在")
    return FileResponse(path, media_type=image.mime_type, filename=image.original_name)


@app.delete("/api/images/{image_id}", status_code=204)
def delete_image(image_id: str, session: DbSession) -> None:
    image = session.get(Image, image_id)
    if image is None:
        raise api_error(404, "IMAGE_NOT_FOUND", "图片不存在")
    settings = get_or_create_settings(session)
    if settings.current_image_id == image_id:
        raise api_error(409, "IMAGE_IN_USE", "当前单图正在使用，不能删除")
    path = image_path(image)
    session.delete(image)
    session.commit()
    path.unlink(missing_ok=True)
    worker.notify_configuration_changed()


@app.get("/api/runs", response_model=RunPage)
def list_runs(
    session: DbSession,
    result: str | None = None,
    trigger: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> RunPage:
    query = select(RunHistory)
    count_query = select(func.count(RunHistory.id))
    if result:
        query = query.where(RunHistory.status == result)
        count_query = count_query.where(RunHistory.status == result)
    if trigger:
        query = query.where(RunHistory.trigger == trigger)
        count_query = count_query.where(RunHistory.trigger == trigger)
    total = session.scalar(count_query) or 0
    rows = session.scalars(
        query.order_by(RunHistory.started_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return RunPage(
        items=[run_to_read(row) for row in rows], total=total, page=page, page_size=page_size
    )


@app.get("/api/runs/{run_id}", response_model=RunRead)
def get_run(run_id: int, session: DbSession) -> RunRead:
    row = session.get(RunHistory, run_id)
    if row is None:
        raise api_error(404, "RUN_NOT_FOUND", "运行记录不存在")
    return run_to_read(row)


@app.get("/api/logs", response_model=LogPage)
def logs(
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    level: str | None = None,
) -> LogPage:
    return read_logs(cursor, limit, level)


@app.post("/api/notifications/wechat-test/test", response_model=WorkerActionResponse)
def test_wechat_notification(session: DbSession) -> WorkerActionResponse:
    settings = get_or_create_settings(session)
    configured = all((
        settings.wechat_test_app_id,
        settings.wechat_test_app_secret,
        settings.wechat_test_template_id,
        settings.wechat_test_openid,
    ))
    if not settings.wechat_test_enabled or not configured:
        raise api_error(
            409,
            "WECHAT_TEST_NOT_CONFIGURED",
            "请先启用并完整配置微信公众号接口测试号",
        )
    config = SimpleNamespace(
        wechat_test_enabled=True,
        wechat_test_app_id=settings.wechat_test_app_id,
        wechat_test_app_secret=settings.wechat_test_app_secret,
        wechat_test_template_id=settings.wechat_test_template_id,
        wechat_test_openid=settings.wechat_test_openid,
    )
    accepted = NotificationService(config).notify(
        "FAFU 签到助手测试",
        "Web 管理台微信公众号接口测试号配置已提交测试",
    )  # type: ignore[arg-type]
    return WorkerActionResponse(
        state=worker.snapshot()["state"],
        message="测试号通知已提交" if accepted else "测试号通知未提交",
    )
if (FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False, response_model=None)
def frontend(full_path: str) -> FileResponse | JSONResponse:
    if full_path == "api" or full_path.startswith("api/"):
        return JSONResponse(
            status_code=404,
            content={"detail": {"code": "NOT_FOUND", "message": "API 接口不存在"}},
        )
    index = FRONTEND_DIST / "index.html"
    requested = (FRONTEND_DIST / full_path).resolve()
    if full_path and FRONTEND_DIST.resolve() in requested.parents and requested.is_file():
        return FileResponse(requested)
    if index.is_file():
        return FileResponse(index)
    return JSONResponse(
        status_code=404,
        content={"detail": {"code": "FRONTEND_NOT_BUILT", "message": "前端尚未构建"}},
    )
