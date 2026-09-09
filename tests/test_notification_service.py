"""微信公众号接口测试号通知服务单元测试。"""

from types import SimpleNamespace
import time
from unittest.mock import patch

from fafu_auto_sign.services.notification_service import NotificationService
from fafu_auto_sign.services.wechat_test_account_service import WeChatTestAccountError


class InlineThread:
    def __init__(self, target, args=(), daemon=None):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self):
        self.target(*self.args)


def config(**overrides):
    values = {
        "wechat_test_enabled": True,
        "wechat_test_app_id": "appid",
        "wechat_test_app_secret": "secret",
        "wechat_test_template_id": "template",
        "wechat_test_openid": "openid",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_notify_starts_wechat_background_thread():
    service = NotificationService(config())
    with patch(
        "fafu_auto_sign.services.notification_service.threading.Thread",
        InlineThread,
    ), patch.object(service, "_send_wechat_notification") as sender:
        assert service.notify("标题", "内容", "task-1", True) is True
    sender.assert_called_once_with(
        "appid", "secret", "template", "openid", "标题", "内容", "task-1", True
    )


def test_disabled_or_incomplete_config_skips_notification():
    assert NotificationService(config(wechat_test_enabled=False)).notify("标题", "内容") is False
    assert NotificationService(config(wechat_test_app_secret=None)).notify("标题", "内容") is False


def test_duplicate_within_five_minutes_is_blocked():
    service = NotificationService(config())
    with patch(
        "fafu_auto_sign.services.notification_service.threading.Thread",
        InlineThread,
    ), patch.object(service, "_send_wechat_notification"):
        assert service.notify("第一次", "内容", "task-1", True) is True
        assert service.notify("第二次", "内容", "task-1", True) is False
        assert service.notify("失败", "内容", "task-1", False) is True


def test_expired_dedup_entry_allows_notification_again():
    service = NotificationService(config())
    service._notification_cache[("task-1", True)] = time.time() - 301
    with patch(
        "fafu_auto_sign.services.notification_service.threading.Thread",
        InlineThread,
    ), patch.object(service, "_send_wechat_notification"):
        assert service.notify("标题", "内容", "task-1", True) is True


def test_notify_without_task_status_does_not_deduplicate():
    service = NotificationService(config())
    with patch(
        "fafu_auto_sign.services.notification_service.threading.Thread",
        InlineThread,
    ), patch.object(service, "_send_wechat_notification"):
        assert service.notify("第一次", "内容") is True
        assert service.notify("第二次", "内容") is True


def test_send_wechat_error_is_logged_without_secret(caplog):
    service = NotificationService(config())
    with patch(
        "fafu_auto_sign.services.notification_service.WeChatTestAccountService.send",
        side_effect=WeChatTestAccountError("upstream"),
    ):
        service._send_wechat_notification(
            "appid", "secret", "template", "openid", "标题", "内容", None, None
        )
    assert "微信测试号通知发送失败" in caplog.text
    assert "secret" not in caplog.text
    assert "openid" not in caplog.text
