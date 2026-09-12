"""Translate per-user Web settings into the existing core AppConfig."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ConfigurationIncomplete
from app.models import Image, Settings, SystemSettings, User
from app.paths import user_image_dir
from app.repository import configuration_state, image_path
from fafu_auto_sign.config import AppConfig

FIXED_BASE_URL = "http://stuhtapi.fafu.edu.cn"


def build_app_config(
    session: Session,
    settings: Settings,
    system: SystemSettings | None = None,
    user: User | None = None,
) -> AppConfig:
    """Create an immutable core configuration snapshot for one user's run."""
    configured, missing = configuration_state(session, settings)
    if not configured or settings.user_token is None:
        raise ConfigurationIncomplete(f"缺少运行配置: {', '.join(missing)}")

    owner = settings.user_id
    image_path_value: str
    image_dir: str | None = None
    latest_image_dir: str | None = None
    if settings.image_mode == "single":
        selected = session.scalar(
            select(Image).where(
                Image.id == settings.current_image_id,
                Image.user_id == owner,
            )
        )
        if selected is None:
            raise ConfigurationIncomplete("当前图片不存在")
        image_path_value = str(image_path(selected))
    else:
        purpose = "library" if settings.image_mode == "library" else "latest"
        selected = session.scalar(
            select(Image)
            .where(Image.purpose == purpose, Image.user_id == owner)
            .order_by(Image.created_at.desc())
        )
        if selected is None:
            raise ConfigurationIncomplete("图片目录为空")
        image_path_value = str(image_path(selected))
        target_dir = str(user_image_dir(owner, purpose)) if owner else str(image_path(selected).parent)
        if purpose == "library":
            image_dir = target_dir
        else:
            latest_image_dir = target_dir

    if system is not None and user is not None:
        notify = bool(
            settings.notification_enabled
            and user.push_available
            and system.wechat_enabled
            and system.wechat_app_id
            and system.wechat_app_secret
            and system.wechat_template_id
            and user.openid
        )
        app_id = system.wechat_app_id
        app_secret = system.wechat_app_secret
        template_id = system.wechat_template_id
        openid = user.openid
        log_level = system.log_level
    else:
        notify = bool(
            settings.wechat_test_enabled
            and settings.wechat_test_app_id
            and settings.wechat_test_app_secret
            and settings.wechat_test_template_id
            and settings.wechat_test_openid
        )
        app_id = settings.wechat_test_app_id
        app_secret = settings.wechat_test_app_secret
        template_id = settings.wechat_test_template_id
        openid = settings.wechat_test_openid
        log_level = settings.log_level

    config = AppConfig(
        user_token=settings.user_token,
        jitter=settings.jitter,
        image_path=image_path_value,
        image_dir=image_dir,
        latest_image_dir=latest_image_dir,
        base_url=FIXED_BASE_URL,
        heartbeat_interval=settings.heartbeat_interval,
        log_level=log_level,
        wechat_test_enabled=notify,
        wechat_test_app_id=app_id,
        wechat_test_app_secret=app_secret,
        wechat_test_template_id=template_id,
        wechat_test_openid=openid,
    )
    return config.model_copy(
        update={"task_keywords": json.loads(settings.task_keywords_json)}
    )


def build_task_query_config(settings: Settings) -> AppConfig:
    if not settings.user_token:
        raise ConfigurationIncomplete("缺少运行配置: user_token")
    return AppConfig(user_token=settings.user_token, base_url=FIXED_BASE_URL)