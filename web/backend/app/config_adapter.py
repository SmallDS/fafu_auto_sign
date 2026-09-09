"""Translate persisted Web settings into the existing core AppConfig."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ConfigurationIncomplete
from app.models import Image, Settings
from app.paths import LATEST_DIR, LIBRARY_DIR
from app.repository import configuration_state, image_path
from fafu_auto_sign.config import AppConfig

FIXED_BASE_URL = "http://stuhtapi.fafu.edu.cn"


def build_app_config(session: Session, settings: Settings) -> AppConfig:
    """Create an immutable core configuration snapshot for one run."""
    configured, missing = configuration_state(session, settings)
    if not configured:
        raise ConfigurationIncomplete(f"缺少运行配置: {', '.join(missing)}")
    if settings.user_token is None:
        raise ConfigurationIncomplete("缺少运行配置: user_token")

    image_path_value: str
    image_dir: str | None = None
    latest_image_dir: str | None = None
    if settings.image_mode == "single":
        selected = session.get(Image, settings.current_image_id)
        if selected is None:
            raise ConfigurationIncomplete("当前图片不存在")
        image_path_value = str(image_path(selected))
    elif settings.image_mode == "library":
        selected = session.scalar(
            select(Image).where(Image.purpose == "library").order_by(Image.created_at.desc())
        )
        if selected is None:
            raise ConfigurationIncomplete("图库为空")
        image_path_value = str(image_path(selected))
        image_dir = str(LIBRARY_DIR)
    else:
        selected = session.scalar(
            select(Image).where(Image.purpose == "latest").order_by(Image.created_at.desc())
        )
        if selected is None:
            raise ConfigurationIncomplete("最新图片队列为空")
        image_path_value = str(image_path(selected))
        latest_image_dir = str(LATEST_DIR)

    return AppConfig(
        user_token=settings.user_token,
        jitter=settings.jitter,
        image_path=image_path_value,
        image_dir=image_dir,
        latest_image_dir=latest_image_dir,
        base_url=FIXED_BASE_URL,
        heartbeat_interval=settings.heartbeat_interval,
        log_level=settings.log_level,
        wechat_test_enabled=settings.wechat_test_enabled,
        wechat_test_app_id=settings.wechat_test_app_id,
        wechat_test_app_secret=settings.wechat_test_app_secret,
        wechat_test_template_id=settings.wechat_test_template_id,
        wechat_test_openid=settings.wechat_test_openid,
        task_keywords=json.loads(settings.task_keywords_json),
    )


def build_task_query_config(settings: Settings) -> AppConfig:
    """Build a read-only FAFU configuration that only requires the persisted Token."""
    if not settings.user_token:
        raise ConfigurationIncomplete("缺少运行配置: user_token")
    return AppConfig(user_token=settings.user_token, base_url=FIXED_BASE_URL)
