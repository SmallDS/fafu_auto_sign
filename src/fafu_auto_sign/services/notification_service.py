"""FAFU 自动签到的微信公众号接口测试号通知服务。"""

import logging
import threading
import time
from typing import Any, Optional

from fafu_auto_sign.services.wechat_test_account_service import (
    WeChatTestAccountError,
    WeChatTestAccountService,
)


class NotificationService:
    """异步发送微信测试号模板消息，并对任务通知做短时去重。"""

    DEDUPLICATION_WINDOW = 300

    def __init__(self, config: Any):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self._notification_cache: dict[tuple[str, bool], float] = {}
        self._cache_lock = threading.Lock()

    def notify(
        self,
        title: str,
        content: str,
        task_id: Optional[str] = None,
        success: Optional[bool] = None,
    ) -> bool:
        """异步提交微信测试号通知；返回值仅表示发送线程是否已启动。"""
        enabled = getattr(self.config, "wechat_test_enabled", False) is True
        values = (
            getattr(self.config, "wechat_test_app_id", None),
            getattr(self.config, "wechat_test_app_secret", None),
            getattr(self.config, "wechat_test_template_id", None),
            getattr(self.config, "wechat_test_openid", None),
        )
        if not enabled or not all(isinstance(value, str) and value for value in values):
            self.logger.debug("微信测试号通知未启用或配置不完整，跳过发送")
            return False

        if task_id is not None and success is not None and not self._should_notify(task_id, success):
            self.logger.debug("任务通知在去重窗口内，跳过")
            return False
        if task_id is not None and success is not None:
            with self._cache_lock:
                self._notification_cache[(task_id, success)] = time.time()

        try:
            threading.Thread(
                target=self._send_wechat_notification,
                args=(*values, title, content, task_id, success),
                daemon=True,
            ).start()
            return True
        except Exception:
            self.logger.error("[x] 启动微信测试号通知线程失败")
            return False

    def notify_summary(self, summary: Any) -> bool:
        """将一次签到执行结果映射为微信测试号通知。"""
        if getattr(summary, "status", None) == "no_task":
            return False
        results = tuple(getattr(summary, "task_results", ()))
        task_id = getattr(results[0], "task_id", None) if results else None
        status = getattr(summary, "status", "failed")
        success = status == "success"
        titles = {
            "success": "FAFU 签到成功",
            "partial": "FAFU 签到部分完成",
            "failed": "FAFU 签到失败",
            "fatal": "FAFU 签到异常",
        }
        content = getattr(summary, "error", None) or titles.get(status, "FAFU 签到执行完成")
        return self.notify(titles.get(status, "FAFU 签到通知"), content, task_id, success)

    def _send_wechat_notification(
        self,
        app_id: str,
        app_secret: str,
        template_id: str,
        openid: str,
        title: str,
        content: str,
        task_id: Optional[str],
        success: Optional[bool],
    ) -> None:
        try:
            WeChatTestAccountService(app_id, app_secret, template_id, openid).send(
                title, content, task_id, success
            )
            self.logger.info("✅ 微信测试号通知发送成功")
        except WeChatTestAccountError:
            self.logger.error("[x] 微信测试号通知发送失败")
        except Exception:
            self.logger.error("[x] 微信测试号通知发送异常")

    def _should_notify(self, task_id: str, success: bool) -> bool:
        """检查任务通知是否处于五分钟去重窗口内。"""
        with self._cache_lock:
            self._cleanup_expired()
            last_time = self._notification_cache.get((task_id, success))
            return (
                last_time is None
                or time.time() - last_time >= self.DEDUPLICATION_WINDOW
            )

    def _cleanup_expired(self) -> None:
        """清理过期去重记录；调用方必须持有缓存锁。"""
        now = time.time()
        expired_keys = [
            key
            for key, timestamp in self._notification_cache.items()
            if now - timestamp >= self.DEDUPLICATION_WINDOW
        ]
        for key in expired_keys:
            del self._notification_cache[key]
