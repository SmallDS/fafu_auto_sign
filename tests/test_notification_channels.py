from types import SimpleNamespace
from unittest.mock import patch

import pytest

from fafu_auto_sign.config import AppConfig
from fafu_auto_sign.services.notification_service import NotificationService


class InlineThread:
    def __init__(self, target, args=(), daemon=None):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


def config(**overrides):
    values = {
        "wechat_test_enabled": False,
        "wechat_test_app_id": None,
        "wechat_test_app_secret": None,
        "wechat_test_template_id": None,
        "wechat_test_openid": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_wechat_channel_dispatches_independently():
    service = NotificationService(config(
        wechat_test_enabled=True,
        wechat_test_app_id="appid",
        wechat_test_app_secret="secret",
        wechat_test_template_id="template",
        wechat_test_openid="openid",
    ))
    with patch(
        "fafu_auto_sign.services.notification_service.threading.Thread",
        InlineThread,
    ), patch.object(service, "_send_wechat_notification") as send_wechat:
        assert service.notify("标题", "内容", "1", True) is True
    send_wechat.assert_called_once()


def test_incomplete_wechat_channel_is_not_accepted():
    service = NotificationService(config(wechat_test_enabled=True, wechat_test_app_id="appid"))
    assert service.notify("标题", "内容") is False


def test_app_config_validates_enabled_wechat_channel():
    with pytest.raises(ValueError, match="完整配置"):
        AppConfig(user_token="2_token", wechat_test_enabled=True)
    configured = AppConfig(
        user_token="2_token",
        wechat_test_enabled=True,
        wechat_test_app_id="appid",
        wechat_test_app_secret="secret",
        wechat_test_template_id="template",
        wechat_test_openid="openid",
    )
    assert configured.wechat_test_enabled is True
    assert configured.notification_enabled is True
    assert "notification_enabled" not in configured.model_dump()
