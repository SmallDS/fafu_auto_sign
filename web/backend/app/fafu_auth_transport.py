"""FAFU CAS/WeLink authentication transport, adapted from fafu-checkin-http.

Only this module talks to the authentication endpoints. It has no global user
credentials or file-backed state; callers own per-user persistence.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import http.cookiejar
import json
import random
import re
import secrets
import string
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import Message
from typing import Literal

from cryptography.hazmat.primitives import hashes, padding as symmetric_padding, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asymmetric_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

CAS_BASE = "http://auth.fafu.edu.cn/authserver"
MAG_BASE = "https://api.welink.huaweicloud.com/mcloud/mag"
API_BASE = "http://stuhtapi.fafu.edu.cn/health-api"
TENANT_ID = "4DFC1E0256214BDC84F39D6E9FF41C38"
SCHOOL_NO = "fafu"
CLIENT_SECRET = "AtPs2O1xEnhwkKDV"
USER_AGENT = "HWorks.Android/7.49.17"

# The WeLink public key is distributed as pubkey.txt by fafu-checkin-http.
# Its three-byte prefix is not part of the DER payload.
_PUBKEY_B64 = (
    "MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEAwjPIz2fKcVofW73dmh9sAi1V2YeN46lhcQo6BcJGNl2NzlK78LwI0Yw7rZwx/oMP5ytIS9dbfd/BEqAF9Nfh2sMwYipXAIuP9TtYeZTvtqLEbl++OmdrKQS/tWXYi7MI/OuKlCH0MnORHcgtxjCAtwc+kjSQx3meVHnRboxNWMGcr7SXPlRNRo8CuuQIJPyHqSq3OdnKYuXFoPM3NnaUyBG61guFkqzyrf19fgcArIRGZL88wT3xHQQGpqSTGzsp52xxB/hUWqZfPLo17qJJyXbeVjUTkitMBR+QjzT/kK+Wb0J7xsrORBFYSYs7g1Sfte2jJs5D/wRZbAtw+6qPVxXXORcYOtJ2Im29AGuoz51I7Gof8J0OQp3TuNTTF/k6ywu9w1+VyGzCuaHcDX1GogOHF27tD3HPRXWgKnIEz7Al1z2ZXnndrXQ95DNgBdQIIOl2GrrqxaTEf8xqeSkc0Bh9v1Ju14BKSw2+8/FTFo0rSaqhdAGFiO7wHI3wc3wzAgMBAAE="
)
_ALLOWED_URLS = {
    ("http", "auth.fafu.edu.cn"),
    ("https", "auth.fafu.edu.cn"),
    ("http", "stuhtapi.fafu.edu.cn"),
    ("https", "api.welink.huaweicloud.com"),
}
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_CAPTCHA_BYTES = 8 * 1024 * 1024
_REQUEST_GAP_SECONDS = 2.0
_request_lock = threading.Lock()
_last_request_at = 0.0
_public_key = serialization.load_der_public_key(base64.b64decode(_PUBKEY_B64))


class FafuAuthTransportError(Exception):
    """An error category safe to display; never contains an upstream response."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class _Response:
    status: int
    body: bytes
    url: str
    headers: Message

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def json(self) -> dict:
        try:
            value = json.loads(self.body)
        except (ValueError, TypeError):
            return {}
        return value if isinstance(value, dict) else {}


def _check_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise FafuAuthTransportError("UPSTREAM_URL_INVALID", "认证服务地址无效") from exc
    if (
        (parsed.scheme, parsed.hostname) not in _ALLOWED_URLS
        or port not in (None, 80 if parsed.scheme == "http" else 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise FafuAuthTransportError("UPSTREAM_URL_INVALID", "认证服务地址无效")


class _RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        _check_url(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and urllib.parse.urlsplit(req.full_url).hostname != urllib.parse.urlsplit(newurl).hostname:
            for name in ("Cookie", "Authorization", "X-Wlk-Authorization", "Referer"):
                redirected.remove_header(name)
        return redirected


def _throttle() -> None:
    global _last_request_at
    with _request_lock:
        remaining = _REQUEST_GAP_SECONDS - (time.monotonic() - _last_request_at)
        if remaining > 0:
            time.sleep(remaining)
        _last_request_at = time.monotonic()


def _read_limited(response, limit: int) -> bytes:
    value = response.read(limit + 1)
    if len(value) > limit:
        raise FafuAuthTransportError("UPSTREAM_RESPONSE_TOO_LARGE", "认证服务响应过大")
    return value


def _send(
    url: str,
    data: dict | str | bytes | None = None,
    *,
    headers: dict[str, str] | None = None,
    opener=None,
    binary: bool = False,
    cas: bool = False,
) -> _Response:
    _check_url(url)
    if isinstance(data, dict):
        body = urllib.parse.urlencode(data).encode("utf-8")
    elif isinstance(data, str):
        body = data.encode("utf-8")
    else:
        body = data
    request = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET")
    request.add_header(
        "User-Agent",
        "Mozilla/5.0 (Linux; Android 12) Mobile Safari/537.36" if cas else USER_AGENT,
    )
    if body is not None:
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    client = opener or urllib.request.build_opener(_RestrictedRedirect())
    _throttle()
    limit = _MAX_CAPTCHA_BYTES if binary else _MAX_RESPONSE_BYTES
    try:
        with client.open(request, timeout=20) as response:
            _check_url(response.url)
            return _Response(response.status, _read_limited(response, limit), response.url, response.headers)
    except urllib.error.HTTPError as exc:
        _check_url(exc.geturl())
        return _Response(exc.code, _read_limited(exc, limit), exc.geturl(), exc.headers)
    except FafuAuthTransportError:
        raise
    except (OSError, ValueError, TimeoutError) as exc:
        raise FafuAuthTransportError("UPSTREAM_UNAVAILABLE", "认证服务暂时不可用") from exc


def _cas(
    url: str,
    data: dict | None = None,
    *,
    opener=None,
    cookie: str | None = None,
    ref: str | None = None,
    xhr: bool = False,
    binary: bool = False,
) -> _Response:
    headers: dict[str, str] = {}
    if cookie:
        headers["Cookie"] = cookie
    if ref:
        _check_url(ref)
        headers["Referer"] = ref
    if xhr:
        headers["X-Requested-With"] = "XMLHttpRequest"
    return _send(url, data, headers=headers, opener=opener, binary=binary, cas=True)


def _random_text(length: int) -> str:
    alphabet = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _aes_cbc(value: str, key: str, iv: str) -> str:
    raw = value.encode("utf-8")
    key_bytes = key.strip().encode("utf-8")
    try:
        padder = symmetric_padding.PKCS7(128).padder()
        padded = padder.update(raw) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key_bytes), modes.CBC(iv.encode("utf-8"))).encryptor()
        return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode("ascii")
    except ValueError as exc:
        raise FafuAuthTransportError("CAS_PAGE_INVALID", "学校登录页面已变化") from exc


def _rsa_tenant() -> str:
    ciphertext = _public_key.encrypt(
        TENANT_ID.encode("utf-8"),
        asymmetric_padding.OAEP(
            mgf=asymmetric_padding.MGF1(hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(ciphertext).decode("ascii")


def _authorization(url: str, token: str = "") -> str:
    timestamp = str(int(time.time()))
    nonce = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    signature = hashlib.md5((CLIENT_SECRET + url + timestamp + nonce).encode("utf-8")).hexdigest()
    return base64.b64encode(f"{timestamp}:{nonce}:{signature}:{token}".encode("utf-8")).decode("ascii")


def _cookie_token(headers: Message) -> str | None:
    for item in headers.get_all("Set-Cookie") or []:
        match = re.match(r"token=([^;]+)", item)
        if match:
            return match.group(1)
    return None


def _tracks(move: int, steps: int = 26) -> list[dict[str, int]]:
    points = [{"a": 0, "b": 0, "c": 0}]
    elapsed = 0
    dy = 0
    for index in range(1, steps):
        progress = 1 - (1 - index / (steps - 1)) ** 2.2
        elapsed += random.randint(20, 50)
        dy += random.choice((0, 0, 0, 1, -1))
        points.append({"a": int(round(move * progress)), "b": dy, "c": elapsed})
    points[-1]["a"] = move
    return points


def _solve_slider(opener, ref: str) -> bool:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise FafuAuthTransportError("CAPTCHA_DEPENDENCY_MISSING", "滑块验证组件未安装") from exc
    for _ in range(5):
        image_response = _cas(CAS_BASE + "/common/openSliderCaptcha.htl", xhr=True, ref=ref, opener=opener)
        try:
            data = image_response.json()
            small_bytes = base64.b64decode(data["smallImage"])
            big_bytes = base64.b64decode(data["bigImage"])
            safe_key = small_bytes[-16:].decode("latin1")
            big = cv2.imdecode(np.frombuffer(big_bytes, np.uint8), cv2.IMREAD_COLOR)
            small = cv2.imdecode(np.frombuffer(small_bytes, np.uint8), cv2.IMREAD_UNCHANGED)
            if big is None or small is None or small.ndim != 3 or small.shape[2] < 4:
                continue
            ys, xs = np.where(small[:, :, 3] > 0)
            if len(xs) == 0:
                continue
            crop = small[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
            result = cv2.matchTemplate(big, crop[:, :, :3], cv2.TM_CCORR_NORMED, mask=crop[:, :, 3])
            _, _, _, location = cv2.minMaxLoc(result)
            base_move = location[0] * 280 / big.shape[1]
        except (KeyError, ValueError, TypeError, AttributeError, binascii.Error, cv2.error):
            continue
        for move in range(int(base_move) + 3, int(base_move) + 8):
            sign = _aes_cbc(
                _random_text(64)
                + json.dumps({"canvasLength": 280, "moveLength": move, "tracks": _tracks(move)}, separators=(",", ":")),
                safe_key,
                _random_text(16),
            )
            result = _cas(
                CAS_BASE + "/common/verifySliderCaptcha.htl",
                {"sign": sign}, xhr=True, ref=ref, opener=opener,
            )
            if result.json().get("errorCode") == 1:
                return True
            time.sleep(0.3)
        time.sleep(2)
    return False


def _solve_image_captcha(opener, ref: str) -> str | None:
    try:
        import ddddocr
    except ImportError as exc:
        raise FafuAuthTransportError("CAPTCHA_DEPENDENCY_MISSING", "图形验证码组件未安装") from exc
    recognizer = ddddocr.DdddOcr(show_ad=False)
    for _ in range(5):
        result = _cas(
            CAS_BASE + f"/getCaptcha.htl?{int(time.time() * 1000)}",
            xhr=True, ref=ref, binary=True, opener=opener,
        )
        if result.status != 200 or not result.body:
            continue
        try:
            candidate = (recognizer.classification(result.body) or "").strip()
        except Exception:
            candidate = ""
        if len(candidate) == 4:
            return candidate
        time.sleep(0.3)
    return None


class FafuAuthTransport:
    """Stateless public interface for one user's CAS and WeLink flow."""

    def begin(self, username: str, password: str) -> tuple[str, str]:
        if not username or not password:
            raise FafuAuthTransportError("CREDENTIALS_REQUIRED", "请填写学号和密码")
        auth_info = _send(
            MAG_BASE + "/FreeProxyForText/wemiddle/api/v1/enterprise/auth/info",
            json.dumps({"tenantid": TENANT_ID}, separators=(",", ":")),
            headers={"Content-Type": "application/json"},
        )
        auth_data = auth_info.json().get("data")
        auth_url = auth_data.get("thirdLoginUrl") if auth_info.status == 200 and isinstance(auth_data, dict) else None
        if not isinstance(auth_url, str) or not auth_url:
            raise FafuAuthTransportError("UPSTREAM_UNAVAILABLE", "无法启动学校登录")
        _check_url(auth_url)
        auth_parts = urllib.parse.urlsplit(auth_url)
        if auth_parts.hostname != "auth.fafu.edu.cn" or auth_parts.path != "/authserver/oauth2.0/authorize":
            raise FafuAuthTransportError("UPSTREAM_URL_INVALID", "学校登录地址无效")
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _RestrictedRedirect())
        page = _cas(auth_url, opener=opener)
        match_salt = re.search(r'pwdEncryptSalt"[^>]*value="([^"]*)"', page.text)
        if page.status != 200 or match_salt is None:
            raise FafuAuthTransportError("UPSTREAM_UNAVAILABLE", "学校登录页面暂时不可用")
        salt = match_salt.group(1)
        match_execution = re.search(r'id="execution"\s+name="execution"\s+value="([^"]*)"', page.text)
        match_lt = re.search(r'id="lt"[^>]*value="([^"]*)"', page.text)
        match_switch = re.search(r'captchaSwitch\s*=\s*"([^"]*)"', page.text)
        captcha_switch = match_switch.group(1) if match_switch else "2"
        check_url = CAS_BASE + "/checkNeedCaptcha.htl?" + urllib.parse.urlencode(
            {"username": username, "_": int(time.time() * 1000)}
        )
        captcha_check = _cas(check_url, xhr=True, ref=page.url, opener=opener)
        captcha_check_data = captcha_check.json()
        if captcha_check.status != 200 or "isNeed" not in captcha_check_data:
            raise FafuAuthTransportError("UPSTREAM_UNAVAILABLE", "学校验证码服务暂时不可用")
        need_captcha = bool(captcha_check_data["isNeed"])
        captcha = ""
        if need_captcha and captcha_switch == "1":
            captcha = _solve_image_captcha(opener, page.url) or ""
            if not captcha:
                raise FafuAuthTransportError("CAPTCHA_FAILED", "图形验证码未通过，请稍后重试")
        elif need_captcha:
            slider_page = _cas(CAS_BASE + "/common/toSliderCaptcha.htl", xhr=True, ref=page.url, opener=opener)
            if slider_page.status != 200 or "sliderDiv" not in slider_page.text or not _solve_slider(opener, page.url):
                raise FafuAuthTransportError("CAPTCHA_FAILED", "滑块验证未通过，请稍后重试")
        login = _cas(
            CAS_BASE + "/login",
            {
                "username": username,
                "password": _aes_cbc(_random_text(64) + password, salt, _random_text(16)),
                "captcha": captcha,
                "_eventId": "submit",
                "cllt": "userNameLogin",
                "dllt": "generalLogin",
                "lt": match_lt.group(1) if match_lt else "",
                "execution": match_execution.group(1) if match_execution else "e1s1",
            },
            ref=page.url,
            opener=opener,
        )
        match_service = re.search(r"service=([^&\"]+)", login.url)
        if match_service is None:
            if login.status != 200:
                raise FafuAuthTransportError("UPSTREAM_UNAVAILABLE", "学校登录服务暂时不可用")
            raise FafuAuthTransportError("INVALID_CREDENTIALS", "学校账号登录失败，请检查学号和密码")
        service = urllib.parse.unquote(match_service.group(1))
        send = _cas(
            CAS_BASE + "/dynamicCode/getDynamicCodeByReauth.do",
            {"userName": username, "authCodeTypeName": "reAuthDynamicCodeType"},
            xhr=True,
            ref=login.url,
            opener=opener,
        )
        if send.status != 200:
            raise FafuAuthTransportError("UPSTREAM_UNAVAILABLE", "短信服务暂时不可用")
        if send.json().get("res") != "success":
            raise FafuAuthTransportError("SMS_SEND_FAILED", "短信验证码发送失败，请稍后重试")
        cookies = "; ".join(f"{cookie.name}={cookie.value}" for cookie in jar if "fafu.edu.cn" in cookie.domain)
        if not cookies:
            raise FafuAuthTransportError("CAS_SESSION_INVALID", "登录会话无效，请重新开始")
        return service, cookies

    def complete(self, service: str, cookie: str, code: str, device_id: str) -> tuple[str, str, str]:
        if not service or not cookie or not code or not device_id:
            raise FafuAuthTransportError("MFA_INPUT_INVALID", "验证码或登录会话不完整")
        ref = CAS_BASE + "/reAuthCheck/reAuthLoginView.do?isMultifactor=true&service=" + urllib.parse.quote(service, safe="")
        mfa = _cas(
            CAS_BASE + "/reAuthCheck/reAuthSubmit.do",
            {
                "service": service, "reAuthType": "3", "isMultifactor": "true",
                "password": "", "dynamicCode": code, "uuid": "", "answer1": "", "answer2": "",
                "otpCode": "", "skipTmpReAuth": "false",
            },
            xhr=True, ref=ref, cookie=cookie,
        )
        if mfa.status != 200:
            raise FafuAuthTransportError("UPSTREAM_UNAVAILABLE", "短信验证服务暂时不可用")
        if "reAuth_success" not in mfa.text:
            raise FafuAuthTransportError("MFA_FAILED", "短信验证码验证失败")
        callback = _cas(
            CAS_BASE + "/login?service=" + urllib.parse.quote(service, safe=""),
            ref=ref, cookie=cookie,
        )
        match_code = re.search(r"[?&]code=([^&\s]+)", callback.url)
        if match_code is None:
            raise FafuAuthTransportError("OAUTH_CODE_MISSING", "登录授权失败，请重新开始")
        oauth_code = urllib.parse.unquote(match_code.group(1))
        welink = _send(
            MAG_BASE + "/v7/callback/LoginReg",
            {"code": oauth_code, "tenantid": _rsa_tenant(), "thirdAuthType": "3", "authType": "phone"},
        )
        we_link_token = _cookie_token(welink.headers)
        refresh_token = welink.json().get("refresh_token")
        if welink.status != 200 or not we_link_token or not isinstance(refresh_token, str) or not refresh_token:
            raise FafuAuthTransportError("UPSTREAM_UNAVAILABLE", "WeLink 登录失败，请稍后重试")
        fafu_token = self.exchange_welink(we_link_token, device_id)
        return we_link_token, refresh_token, fafu_token

    def refresh_welink(self, refresh_token: str) -> tuple[str, str]:
        if not refresh_token:
            raise FafuAuthTransportError("INVALID_REFRESH", "需要重新连接 FAFU 账号")
        response = _send(
            MAG_BASE + "/v7/refresh/LoginReg",
            {"refresh_token": refresh_token, "thirdAuthType": "3", "tenantid": _rsa_tenant()},
        )
        we_link_token = _cookie_token(response.headers)
        new_refresh_token = response.json().get("refresh_token")
        if response.status != 200 or not we_link_token or not isinstance(new_refresh_token, str) or not new_refresh_token:
            error_text = " ".join(str(response.json().get(key, "")) for key in ("errorCode", "errorMessage", "message"))
            if response.status == 401 or re.search(
                r"(?:refresh[_ -]?token|刷新令牌).{0,30}(?:invalid|expired|过期|失效|无效)",
                error_text, re.I,
            ):
                raise FafuAuthTransportError("INVALID_REFRESH", "FAFU 会话已失效，请重新连接")
            raise FafuAuthTransportError("UPSTREAM_UNAVAILABLE", "FAFU 会话续期暂时失败")
        return we_link_token, new_refresh_token

    def exchange_welink(self, we_link_token: str, device_id: str) -> str:
        if not we_link_token or not device_id:
            raise FafuAuthTransportError("UPSTREAM_UNAVAILABLE", "FAFU 会话不完整")
        authcode = _send(
            MAG_BASE + "/ProxyForText/sso/auth/v2/code",
            json.dumps({"codeType": "h5", "codeInfo": "stuhealth.fafu.edu.cn"}, separators=(",", ":")),
            headers={"Content-Type": "application/json", "x-wlk-Authorization": we_link_token},
        )
        code = authcode.json().get("code")
        if authcode.status != 200 or not isinstance(code, str) or not code:
            raise FafuAuthTransportError("UPSTREAM_UNAVAILABLE", "无法获取 FAFU 授权码")
        url = API_BASE + "/third_party/welink/login"
        response = _send(
            url,
            {"schoolNo": SCHOOL_NO, "clientType": 1, "code": code, "deviceId": device_id},
            headers={"Authorization": _authorization(url)},
        )
        payload = response.json()
        login_data = payload.get("userLoginResp")
        token = login_data.get("token") if isinstance(login_data, dict) else None
        if response.status != 200 or payload.get("isRegister") != 1 or not isinstance(token, str) or not token.startswith("2_"):
            message = payload.get("message")
            if isinstance(message, str) and ("同一台手机" in message or "设备" in message and "绑定" in message):
                raise FafuAuthTransportError("DEVICE_MISMATCH", "设备 ID 与 FAFU 账号绑定设备不一致")
            if response.status == 408:
                raise FafuAuthTransportError("CLOCK_ERROR", "系统时间不同步")
            raise FafuAuthTransportError("UPSTREAM_UNAVAILABLE", "FAFU 登录暂时失败")
        return token

    def validate_token(self, token: str) -> Literal["valid", "expired", "clock_error", "unavailable"]:
        if not token.startswith("2_"):
            return "expired"
        url = API_BASE + "/sign_in/student/my/page"
        try:
            response = _send(
                url + "?rows=1&pageNum=1",
                b"",
                headers={"Authorization": _authorization(url, token)},
            )
        except FafuAuthTransportError:
            return "unavailable"
        if response.status == 401:
            return "expired"
        if response.status == 408:
            return "clock_error"
        if response.status == 200:
            return "valid" if "records" in response.json() else "expired"
        return "unavailable"
