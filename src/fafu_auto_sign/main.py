"""FAFU Auto Sign 的命令行守护进程入口。"""

import argparse
import logging

from fafu_auto_sign.client import FAFUClient
from fafu_auto_sign.config import load_config
from fafu_auto_sign.executor import SignExecutor
from fafu_auto_sign.graceful_shutdown import GracefulShutdown
from fafu_auto_sign.logging_config import setup_logging
from fafu_auto_sign.services import SignService, TaskService
from fafu_auto_sign.services.notification_service import NotificationService
from fafu_auto_sign.services.upload_service import UploadService


def run(config_path: str = "config.json") -> None:
    """加载 JSON/环境变量配置并运行自动签到守护进程。

    CLI 不捕获底层客户端针对 401/408 抛出的 ``SystemExit``，因此继续
    保持致命认证/时间错误立即退出的行为。普通网络和业务错误由单轮执行器
    记录为失败结果，守护进程会在配置的心跳间隔后继续尝试。
    """
    config = load_config(config_path)

    notification_service = None
    if config.notification_enabled:
        notification_service = NotificationService(config)

    setup_logging(config.log_level, notification_service=notification_service)
    logger = logging.getLogger(__name__)

    with FAFUClient(config) as client:
        task_service = TaskService(client, config)
        upload_service = UploadService(client)
        sign_service = SignService(client, config)
        executor = SignExecutor(
            config,
            client=client,
            task_service=task_service,
            upload_service=upload_service,
            sign_service=sign_service,
        )

        shutdown = GracefulShutdown()
        shutdown.register_cleanup(executor.close)

        logger.info("启动自动保活与签到守护进程...")

        while not shutdown.is_stopped():
            summary = executor.execute_once(trigger="scheduled", capture_fatal=False)

            if summary.status == "no_task":
                logger.info(f"心跳保活成功，未发现任务。睡眠 {config.heartbeat_interval} 秒...")
            elif summary.status in {"failed", "partial"} and summary.error:
                logger.warning(f"本轮执行结果为 {summary.status}: {summary.error}")

            if shutdown.wait(config.heartbeat_interval):
                break

        executor.close()
        logger.info("守护进程已停止")


def main() -> None:
    """安装后的 ``fafu-auto-sign`` 控制台命令入口。"""
    parser = argparse.ArgumentParser(description="FAFU自动签到助手")
    parser.add_argument(
        "--config", "-c", default="config.json", help="配置文件路径 (默认: config.json)"
    )
    args = parser.parse_args()

    try:
        run(args.config)
    except KeyboardInterrupt:
        print("\n程序被用户中断")
        raise SystemExit(0)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"程序异常退出: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
