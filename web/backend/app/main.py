"""FastAPI application, authenticated user APIs and static frontend."""

from __future__ import annotations

import logging
import shutil
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Annotated, AsyncIterator, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.admin_routes import router as admin_router
from app.amap_proxy import (
    AmapProxyError,
    AmapResponseTooLarge,
    AmapUpstreamUnavailable,
    UnsupportedAmapPath,
    install_amap_access_log_filter,
    proxy_amap_request,
)
from app.auth import ActiveUser, AdminUser, SESSION_COOKIE, check_csrf
from app.auth_routes import router as auth_router
from app.database import SessionLocal, get_db, run_migrations
from app.errors import ConfigurationIncomplete, api_error
from app.image_store import MAX_UPLOAD_FILES, InvalidImage, store_upload
from app.log_reader import read_logs
from app.manual_sign import (
    ExecutionBusy,
    ManualSignService,
    TaskDetailsUnavailable,
    TaskNoLongerActive,
    UpstreamUnavailable,
)
from app.models import Image, RunHistory, SignJob, User
from app.paths import FRONTEND_DIST, IMAGE_ROOT, LOG_DIR, ensure_data_directories
from app.repository import (
    audit,
    configuration_state,
    get_meta,
    get_or_create_settings,
    get_or_create_system_settings,
    image_path,
    image_to_read,
    latest_run,
    run_to_read,
    seven_day_stats,
    set_meta,
    settings_to_read,
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
from app.wechat import normalize_wechat_text
from app.worker import WorkerManager
from fafu_auto_sign.logging_config import setup_logging
from fafu_auto_sign.services.notification_service import NotificationService

logger = logging.getLogger(__name__)
worker = WorkerManager()
manual_sign = ManualSignService(worker)
DbSession = Annotated[Session, Depends(get_db)]


def _repair_user_nicknames(session: Session) -> None:
    changed = False
    for user in session.scalars(select(User).where(User.nickname.is_not(None))):
        repaired = normalize_wechat_text(user.nickname)
        if repaired != user.nickname:
            user.nickname = repaired[:64]
            changed = True
    if changed:
        session.commit()


def _clear_legacy_business_files(session: Session) -> None:
    if get_meta(session, "multi_user_files_cleared") == "1":
        return
    if IMAGE_ROOT.exists():
        shutil.rmtree(IMAGE_ROOT)
    if LOG_DIR.exists():
        for path in LOG_DIR.iterdir():
            if path.is_file():
                path.unlink(missing_ok=True)
    set_meta(session, "multi_user_files_cleared", "1")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    ensure_data_directories()
    run_migrations()
    with SessionLocal() as session:
        _clear_legacy_business_files(session)
        _repair_user_nicknames(session)
        system = get_or_create_system_settings(session)
        log_level = system.log_level
    setup_logging(log_level, log_dir=str(LOG_DIR))
    install_amap_access_log_filter()
    worker.start()
    try:
        yield
    finally:
        worker.stop()


app = FastAPI(title="FAFU Auto Sign Web", version="2.0.0", lifespan=lifespan)


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    public_write = (
        request.url.path.startswith("/api/bootstrap/")
        or request.url.path == "/api/auth/pairings"
        or (
            request.url.path.startswith("/api/auth/pairings/")
            and request.url.path.endswith("/exchange")
        )
    )
    if (
        request.method not in {"GET", "HEAD", "OPTIONS"}
        and request.cookies.get(SESSION_COOKIE)
        and not public_write
    ):
        try:
            with SessionLocal() as session:
                check_csrf(request, session)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    fields: dict[str, str] = {}
    for error in exc.errors():
        location = error.get("loc", ())
        key = str(location[-1]) if location else "request"
        fields[key] = str(error.get("msg", "输入无效"))
    return JSONResponse(
        status_code=422,
        content={"detail": {
            "code": "VALIDATION_ERROR",
            "message": "请求参数校验失败",
            "fields": fields,
        }},
    )


app.include_router(auth_router)
app.include_router(admin_router)


@app.get("/api/health", response_model=HealthResponse)
def health(session: DbSession) -> HealthResponse:
    session.execute(text("SELECT 1"))
    system = get_or_create_system_settings(session)
    return HealthResponse(
        worker_state=worker.snapshot()["state"],
        configured=system.setup_state == "initialized",
        setup_state=system.setup_state,
    )


@app.get("/api/settings", response_model=SettingsRead)
def get_settings(user: ActiveUser, session: DbSession) -> SettingsRead:
    return settings_to_read(session, get_or_create_settings(session, user.id))


@app.put("/api/settings", response_model=SettingsRead)
def put_settings(
    payload: SettingsUpdate, user: ActiveUser, session: DbSession
) -> SettingsRead:
    try:
        settings = update_settings(session, payload, user.id)
    except ValueError as exc:
        session.rollback()
        raise api_error(
            422, "VALIDATION_ERROR", "配置校验失败", {"settings": str(exc)}
        ) from exc
    worker.notify_configuration_changed()
    return settings_to_read(session, settings)


@app.get("/api/map/config", response_model=MapConfigRead)
def map_config(user: ActiveUser, session: DbSession) -> MapConfigRead:
    system = get_or_create_system_settings(session)
    settings = get_or_create_settings(session, user.id)
    enabled = bool(
        system.amap_enabled and system.amap_js_key and system.amap_security_js_code
    )
    return MapConfigRead(
        enabled=enabled,
        js_key=system.amap_js_key if enabled else None,
        jitter=settings.jitter,
    )


@app.get("/_AMapService/{service_path:path}", response_model=None)
def amap_service_proxy(
    service_path: str,
    request: Request,
    user: ActiveUser,
    session: DbSession,
) -> Response:
    system = get_or_create_system_settings(session)
    if not (
        system.amap_enabled and system.amap_js_key and system.amap_security_js_code
    ):
        raise api_error(409, "AMAP_NOT_CONFIGURED", "高德地图尚未启用或配置不完整")
    try:
        return proxy_amap_request(
            service_path,
            request.query_params.multi_items(),
            system.amap_security_js_code,
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
def status(user: ActiveUser, session: DbSession) -> StatusResponse:
    settings = get_or_create_settings(session, user.id)
    configured, _ = configuration_state(session, settings)
    snapshot = worker.snapshot(user.id)
    latest = latest_run(session, user.id)
    return StatusResponse(
        configured=configured,
        worker_state=snapshot["state"],
        last_check_at=snapshot["last_check_at"],
        next_check_at=snapshot["next_check_at"],
        last_error=latest.error if latest else None,
        recent_run=run_to_read(latest) if latest else None,
        stats_7d=seven_day_stats(session, user.id),
    )


@app.post("/api/worker/pause", response_model=WorkerActionResponse)
def pause_worker(user: ActiveUser, session: DbSession) -> WorkerActionResponse:
    settings = get_or_create_settings(session, user.id)
    settings.worker_enabled = False
    settings.config_version += 1
    for job in session.scalars(
        select(SignJob).where(
            SignJob.user_id == user.id,
            SignJob.kind == "scheduled",
            SignJob.status == "queued",
        )
    ):
        job.status = "cancelled"
    session.commit()
    worker.notify_configuration_changed()
    return WorkerActionResponse(state="paused", message="当前任务结束后将暂停自动检查")


@app.post("/api/worker/resume", response_model=WorkerActionResponse)
def resume_worker(user: ActiveUser, session: DbSession) -> WorkerActionResponse:
    settings = get_or_create_settings(session, user.id)
    configured, missing = configuration_state(session, settings)
    if not configured:
        raise api_error(
            409,
            "CONFIGURATION_INCOMPLETE",
            "配置不完整，无法恢复",
            {"missing": ",".join(missing)},
        )
    settings.worker_enabled = True
    settings.next_run_at = None
    settings.config_version += 1
    session.commit()
    worker.notify_configuration_changed()
    return WorkerActionResponse(state="idle", message="已恢复自动检查")


@app.post("/api/worker/run-now", response_model=WorkerActionResponse, status_code=202)
def run_now(user: ActiveUser, session: DbSession) -> WorkerActionResponse:
    configured, missing = configuration_state(
        session, get_or_create_settings(session, user.id)
    )
    if not configured:
        raise api_error(
            409,
            "CONFIGURATION_INCOMPLETE",
            "配置不完整，无法执行",
            {"missing": ",".join(missing)},
        )
    job_id = worker.enqueue_run(user.id)
    if not job_id:
        raise api_error(409, "WORKER_BUSY", "该用户已有签到任务正在排队或执行")
    return WorkerActionResponse(state="queued", message="已加入立即检查队列", job_id=job_id)


@app.get("/api/sign-tasks", response_model=SignTaskPage)
def list_sign_tasks(
    user: ActiveUser,
    session: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> SignTaskPage:
    try:
        result = manual_sign.list_tasks(session, page, page_size, user_id=user.id)
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
def get_sign_task_details(
    task_id: int, user: ActiveUser, session: DbSession
) -> SignTaskDetailsRead:
    try:
        details = manual_sign.get_details(session, task_id, user_id=user.id)
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
    user: ActiveUser,
    session: DbSession,
) -> RunRead:
    try:
        row = manual_sign.submit(
            session,
            task_id,
            payload.source_page,
            payload.page_size,
            user_id=user.id,
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
    user: ActiveUser,
    session: DbSession,
    category: Literal["library", "latest"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ImagePage:
    count_query = select(func.count(Image.id)).where(Image.user_id == user.id)
    images_query = select(Image).where(Image.user_id == user.id)
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
        items=[image_to_read(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@app.post("/api/images", response_model=list[ImageRead], status_code=201)
async def upload_images(
    user: ActiveUser,
    session: DbSession,
    files: Annotated[list[UploadFile], File(...)],
    category: Annotated[Literal["library", "latest"], Form()] = "library",
) -> list[ImageRead]:
    if len(files) > MAX_UPLOAD_FILES:
        raise api_error(413, "TOO_MANY_FILES", "每次最多上传 10 张图片")
    created: list[Image] = []
    try:
        for upload in files:
            created.append(
                await store_upload(
                    session, upload, category, user_id=user.id, commit=False
                )
            )
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
def get_image(image_id: str, user: ActiveUser, session: DbSession) -> FileResponse:
    image = session.scalar(
        select(Image).where(Image.id == image_id, Image.user_id == user.id)
    )
    if image is None:
        raise api_error(404, "IMAGE_NOT_FOUND", "图片不存在")
    path = image_path(image)
    if not path.is_file():
        raise api_error(404, "IMAGE_FILE_MISSING", "图片文件不存在")
    return FileResponse(path, media_type=image.mime_type, filename=image.original_name)


@app.delete("/api/images/{image_id}", status_code=204)
def delete_image(image_id: str, user: ActiveUser, session: DbSession) -> None:
    image = session.scalar(
        select(Image).where(Image.id == image_id, Image.user_id == user.id)
    )
    if image is None:
        raise api_error(404, "IMAGE_NOT_FOUND", "图片不存在")
    settings = get_or_create_settings(session, user.id)
    if settings.current_image_id == image_id:
        raise api_error(409, "IMAGE_IN_USE", "当前单图正在使用，不能删除")
    path = image_path(image)
    session.delete(image)
    session.commit()
    path.unlink(missing_ok=True)
    worker.notify_configuration_changed()


@app.get("/api/runs", response_model=RunPage)
def list_runs(
    user: ActiveUser,
    session: DbSession,
    result: str | None = None,
    trigger: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> RunPage:
    query = select(RunHistory).where(RunHistory.user_id == user.id)
    count_query = select(func.count(RunHistory.id)).where(
        RunHistory.user_id == user.id
    )
    if result:
        query = query.where(RunHistory.status == result)
        count_query = count_query.where(RunHistory.status == result)
    if trigger:
        query = query.where(RunHistory.trigger == trigger)
        count_query = count_query.where(RunHistory.trigger == trigger)
    total = session.scalar(count_query) or 0
    rows = session.scalars(
        query.order_by(RunHistory.started_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return RunPage(
        items=[run_to_read(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@app.get("/api/runs/{run_id}", response_model=RunRead)
def get_run(run_id: int, user: ActiveUser, session: DbSession) -> RunRead:
    row = session.scalar(
        select(RunHistory).where(
            RunHistory.id == run_id, RunHistory.user_id == user.id
        )
    )
    if row is None:
        raise api_error(404, "RUN_NOT_FOUND", "运行记录不存在")
    return run_to_read(row)


@app.get("/api/logs", response_model=LogPage)
def logs(
    admin: AdminUser,
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    level: str | None = None,
) -> LogPage:
    return read_logs(cursor, limit, level)


@app.post("/api/notifications/wechat-test/test", response_model=WorkerActionResponse)
def test_wechat_notification(
    user: ActiveUser, session: DbSession
) -> WorkerActionResponse:
    settings = get_or_create_settings(session, user.id)
    system = get_or_create_system_settings(session)
    configured = all(
        (
            system.wechat_app_id,
            system.wechat_app_secret,
            system.wechat_template_id,
            user.openid,
        )
    )
    if not settings.notification_enabled or not system.wechat_enabled or not configured:
        raise api_error(
            409,
            "WECHAT_TEST_NOT_CONFIGURED",
            "系统微信测试号通知尚未配置或当前用户已关闭通知",
        )
    config = SimpleNamespace(
        wechat_test_enabled=True,
        wechat_test_app_id=system.wechat_app_id,
        wechat_test_app_secret=system.wechat_app_secret,
        wechat_test_template_id=system.wechat_template_id,
        wechat_test_openid=user.openid,
    )
    accepted = NotificationService(config).notify(
        "FAFU 签到助手测试",
        "Web 管理台微信公众号测试号配置已提交测试",
    )
    return WorkerActionResponse(
        state=worker.snapshot(user.id)["state"],
        message="测试号通知已提交" if accepted else "测试号通知未提交",
    )


@app.post("/api/admin/users/{user_id}/worker/pause", response_model=WorkerActionResponse)
def admin_pause_user_worker(
    user_id: str, admin: AdminUser, session: DbSession
) -> WorkerActionResponse:
    target = session.get(User, user_id)
    if target is None:
        raise api_error(404, "USER_NOT_FOUND", "用户不存在")
    settings = get_or_create_settings(session, user_id)
    settings.worker_enabled = False
    settings.config_version += 1
    for job in session.scalars(
        select(SignJob).where(
            SignJob.user_id == user_id,
            SignJob.status == "queued",
        )
    ):
        job.status = "cancelled"
    audit(
        session,
        admin.id,
        "user.worker.pause",
        target_user_id=user_id,
        commit=False,
    )
    session.commit()
    worker.notify_configuration_changed()
    return WorkerActionResponse(
        state="paused", message="当前任务结束后将暂停该用户自动检查"
    )


@app.post("/api/admin/users/{user_id}/worker/resume", response_model=WorkerActionResponse)
def admin_resume_user_worker(
    user_id: str, admin: AdminUser, session: DbSession
) -> WorkerActionResponse:
    target = session.get(User, user_id)
    if target is None or target.status != "active":
        raise api_error(404, "USER_NOT_ACTIVE", "用户不存在或不可执行")
    settings = get_or_create_settings(session, user_id)
    configured, missing = configuration_state(session, settings)
    if not configured:
        raise api_error(
            409,
            "CONFIGURATION_INCOMPLETE",
            "配置不完整，无法恢复",
            {"missing": ",".join(missing)},
        )
    settings.worker_enabled = True
    settings.next_run_at = None
    settings.config_version += 1
    audit(
        session,
        admin.id,
        "user.worker.resume",
        target_user_id=user_id,
        commit=False,
    )
    session.commit()
    worker.notify_configuration_changed()
    return WorkerActionResponse(state="idle", message="已恢复该用户自动检查")


@app.post("/api/admin/users/{user_id}/worker/run-now", response_model=WorkerActionResponse)
def admin_run_user_now(
    user_id: str, admin: AdminUser, session: DbSession
) -> WorkerActionResponse:
    target = session.get(User, user_id)
    if target is None or target.status != "active":
        raise api_error(404, "USER_NOT_ACTIVE", "用户不存在或不可执行")
    job_id = worker.enqueue_run(user_id)
    if not job_id:
        raise api_error(409, "WORKER_BUSY", "该用户已有任务或配置不完整")
    return WorkerActionResponse(
        state="queued", message="用户签到任务已加入队列", job_id=job_id
    )


@app.get("/api/admin/stats")
def admin_stats(admin: AdminUser, session: DbSession) -> dict[str, int]:
    return {
        "users": session.scalar(select(func.count(User.id))) or 0,
        "pending": session.scalar(
            select(func.count(User.id)).where(User.status == "pending")
        )
        or 0,
        "active": session.scalar(
            select(func.count(User.id)).where(User.status == "active")
        )
        or 0,
        "queued_jobs": session.scalar(
            select(func.count(SignJob.id)).where(SignJob.status == "queued")
        )
        or 0,
    }


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
    if (
        full_path
        and FRONTEND_DIST.resolve() in requested.parents
        and requested.is_file()
    ):
        return FileResponse(requested)
    if index.is_file():
        return FileResponse(index)
    return JSONResponse(
        status_code=404,
        content={
            "detail": {"code": "FRONTEND_NOT_BUILT", "message": "前端尚未构建"}
        },
    )