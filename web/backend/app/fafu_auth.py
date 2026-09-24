"""User-scoped FAFU CAS binding and WeLink token renewal."""

from __future__ import annotations

import secrets
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.errors import redact_sensitive_text
from app.models import FafuAuthSession, Settings, User, utcnow
from app.repository import get_or_create_settings
from app.fafu_auth_transport import FafuAuthTransport, FafuAuthTransportError

ATTEMPT_TTL = timedelta(minutes=5)
START_WINDOW = timedelta(minutes=10)
MAX_STARTS = 3
BACKOFF_SECONDS = (60, 300, 1800, 7200)


class FafuAuthError(RuntimeError):
    """A safe, user-facing authentication error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LoginAttempt:
    id: str
    user_id: str
    username: str
    password: str
    device_id: str
    service: str
    cookie: str
    expires_at: datetime


class FafuAuthManager:
    """Keep MFA cookies ephemeral and serialize each user's token rotation."""

    def __init__(self, transport: FafuAuthTransport | None = None) -> None:
        self.transport = transport or FafuAuthTransport()
        self._guard = threading.RLock()
        self._user_locks: dict[str, threading.RLock] = defaultdict(threading.RLock)
        self._attempts: dict[str, LoginAttempt] = {}
        self._starts: dict[str, deque[datetime]] = defaultdict(deque)

    def _lock_for(self, user_id: str) -> threading.RLock:
        with self._guard:
            return self._user_locks[user_id]

    def user_lock(self, user_id: str) -> threading.RLock:
        """Serialize credential switches with binding and token rotation."""
        return self._lock_for(user_id)

    def _begin(
        self, user_id: str, username: str, password: str, device_id: str
    ) -> LoginAttempt:
        with self._lock_for(user_id):
            now = utcnow()
            with self._guard:
                self._attempts = {
                    key: value for key, value in self._attempts.items()
                    if value.expires_at > now
                }
                starts = self._starts[user_id]
                while starts and starts[0] <= now - START_WINDOW:
                    starts.popleft()
                if len(starts) >= MAX_STARTS:
                    raise FafuAuthError("AUTH_RATE_LIMITED", "请求过于频繁，请稍后再试")
                starts.append(now)
                self._attempts = {
                    key: value for key, value in self._attempts.items()
                    if value.user_id != user_id
                }
            try:
                service, cookie = self.transport.begin(username, password)
            except FafuAuthTransportError as exc:
                raise FafuAuthError(exc.code, exc.message) from exc
            attempt = LoginAttempt(
                id=secrets.token_urlsafe(32), user_id=user_id,
                username=username, password=password, device_id=device_id,
                service=service, cookie=cookie, expires_at=utcnow() + ATTEMPT_TTL,
            )
            with self._guard:
                self._attempts[attempt.id] = attempt
            return attempt

    def start(
        self, user_id: str, username: str, password: str, device_id: str
    ) -> LoginAttempt:
        return self._begin(user_id, username, password, device_id)

    def reconnect(self, session: Session, user_id: str) -> LoginAttempt:
        auth = session.get(FafuAuthSession, user_id)
        settings = get_or_create_settings(session, user_id)
        if auth is None or settings.fafu_auth_mode != "auto":
            raise FafuAuthError("AUTH_NOT_CONNECTED", "请先绑定 FAFU 账号")
        return self._begin(user_id, auth.username, auth.password, auth.device_id)

    def cancel(self, user_id: str, attempt_id: str) -> None:
        with self._guard:
            attempt = self._attempts.get(attempt_id)
            if attempt is None or attempt.user_id != user_id:
                raise FafuAuthError("AUTH_ATTEMPT_NOT_FOUND", "验证已失效，请重新开始")
            del self._attempts[attempt_id]

    def invalidate_user(self, user_id: str) -> None:
        """Discard unfinished MFA when a user chooses a manual token."""
        with self._guard:
            self._attempts = {
                key: value for key, value in self._attempts.items()
                if value.user_id != user_id
            }

    def complete(
        self, session: Session, user_id: str, attempt_id: str, code: str
    ) -> Settings:
        with self._lock_for(user_id):
            session.expire_all()
            user = session.get(User, user_id)
            if user is None or user.status != "active":
                raise FafuAuthError("AUTH_REQUIRED", "当前账号不可连接 FAFU")
            with self._guard:
                attempt = self._attempts.get(attempt_id)
                if attempt is None or attempt.user_id != user_id:
                    raise FafuAuthError("AUTH_ATTEMPT_NOT_FOUND", "验证已失效，请重新开始")
                del self._attempts[attempt_id]
            if attempt.expires_at <= utcnow():
                raise FafuAuthError("AUTH_ATTEMPT_EXPIRED", "验证码会话已过期，请重新开始")
            try:
                we_link_token, refresh_token, fafu_token = self.transport.complete(
                    attempt.service, attempt.cookie, code, attempt.device_id
                )
            except FafuAuthTransportError as exc:
                raise FafuAuthError(exc.code, exc.message) from exc
            if not fafu_token.startswith("2_") or not refresh_token:
                raise FafuAuthError("TOKEN_INVALID", "未取得有效 FAFU Token")
            try:
                validity = self.transport.validate_token(fafu_token)
            except FafuAuthTransportError as exc:
                raise FafuAuthError(exc.code, exc.message) from exc
            if validity != "valid":
                code = "CLOCK_ERROR" if validity == "clock_error" else "TOKEN_INVALID"
                raise FafuAuthError(code, "FAFU Token 校验失败，请重新连接")
            auth = session.get(FafuAuthSession, user_id)
            if auth is None:
                auth = FafuAuthSession(
                    user_id=user_id, username=attempt.username,
                    password=attempt.password, device_id=attempt.device_id,
                )
                session.add(auth)
            resume_worker = auth.resume_worker_after_reconnect
            auth.username = attempt.username
            auth.password = attempt.password
            auth.device_id = attempt.device_id
            auth.we_link_token = we_link_token
            auth.refresh_token = refresh_token
            auth.refresh_fail = 0
            auth.next_refresh_after = None
            auth.last_refresh_at = utcnow()
            auth.last_error = None
            auth.reconnect_required = False
            auth.resume_worker_after_reconnect = False
            settings = get_or_create_settings(session, user_id)
            settings.fafu_auth_mode = "auto"
            settings.user_token = fafu_token
            settings.config_version += 1
            settings.next_run_at = utcnow()
            if resume_worker:
                settings.worker_enabled = True
            session.commit()
            session.refresh(settings)
            return settings

    def _mark_reconnect(
        self, session: Session, auth: FafuAuthSession, settings: Settings
    ) -> None:
        auth.reconnect_required = True
        auth.last_error = "FAFU 登录已失效，请重新连接"
        auth.next_refresh_after = None
        auth.resume_worker_after_reconnect = settings.worker_enabled
        settings.worker_enabled = False
        session.commit()

    def _mark_backoff(
        self, session: Session, auth: FafuAuthSession, message: str
    ) -> None:
        auth.refresh_fail = min(auth.refresh_fail + 1, len(BACKOFF_SECONDS))
        auth.next_refresh_after = utcnow() + timedelta(
            seconds=BACKOFF_SECONDS[auth.refresh_fail - 1]
        )
        auth.last_error = redact_sensitive_text(message, "令牌续期失败")
        session.commit()

    def ensure_token(
        self, session: Session, user_id: str, *, force_refresh: bool = False
    ) -> str:
        """Validate a stored token and renew it when expired, under a user lock."""
        with self._lock_for(user_id):
            session.expire_all()
            settings = get_or_create_settings(session, user_id)
            if settings.fafu_auth_mode != "auto":
                if not settings.user_token:
                    raise FafuAuthError("TOKEN_MISSING", "请先配置 FAFU Token")
                return settings.user_token
            auth = session.get(FafuAuthSession, user_id)
            if auth is None or auth.reconnect_required:
                raise FafuAuthError("RECONNECT_REQUIRED", "请重新连接 FAFU 账号")
            if not force_refresh and settings.user_token:
                try:
                    validity = self.transport.validate_token(settings.user_token)
                except FafuAuthTransportError as exc:
                    raise FafuAuthError(exc.code, exc.message) from exc
                if validity == "valid":
                    return settings.user_token
                if validity == "clock_error":
                    raise FafuAuthError("CLOCK_ERROR", "系统时间校验失败")
                if validity == "unavailable":
                    raise FafuAuthError("UPSTREAM_UNAVAILABLE", "FAFU 服务暂时不可用")
            retry_at = auth.next_refresh_after
            if retry_at is not None:
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                if retry_at > utcnow():
                    raise FafuAuthError("REFRESH_BACKOFF", "令牌续期暂缓，请稍后重试")
            if not auth.refresh_token:
                self._mark_reconnect(session, auth, settings)
                raise FafuAuthError("RECONNECT_REQUIRED", "请重新连接 FAFU 账号")
            try:
                we_link_token, new_refresh_token = self.transport.refresh_welink(
                    auth.refresh_token
                )
            except FafuAuthTransportError as exc:
                if exc.code == "INVALID_REFRESH":
                    self._mark_reconnect(session, auth, settings)
                    raise FafuAuthError("RECONNECT_REQUIRED", "请重新连接 FAFU 账号") from exc
                self._mark_backoff(session, auth, exc.message)
                raise FafuAuthError(exc.code, exc.message) from exc
            if not new_refresh_token:
                self._mark_backoff(session, auth, "未取得新的刷新令牌")
                raise FafuAuthError("TOKEN_INVALID", "令牌续期失败")
            auth.we_link_token = we_link_token
            auth.refresh_token = new_refresh_token
            session.commit()
            try:
                token = self.transport.exchange_welink(we_link_token, auth.device_id)
            except FafuAuthTransportError as exc:
                self._mark_backoff(session, auth, exc.message)
                raise FafuAuthError(exc.code, exc.message) from exc
            if not token.startswith("2_"):
                self._mark_backoff(session, auth, "FAFU 返回的 Token 格式无效")
                raise FafuAuthError("TOKEN_INVALID", "令牌续期失败")
            settings.user_token = token
            settings.config_version += 1
            settings.next_run_at = utcnow()
            auth.refresh_fail = 0
            auth.next_refresh_after = None
            auth.last_refresh_at = utcnow()
            auth.last_error = None
            session.commit()
            return token


fafu_auth = FafuAuthManager()
