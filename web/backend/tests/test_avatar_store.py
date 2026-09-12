from __future__ import annotations

from io import BytesIO

import pytest
import requests
from PIL import Image

import app.avatar_store as avatar_store


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 4), "red").save(output, format="PNG")
    return output.getvalue()


def response(status: int, *, location: str | None = None, content: bytes = b"") -> requests.Response:
    item = requests.Response()
    item.status_code = status
    item._content = content
    item.raw = BytesIO(content)
    if location:
        item.headers["location"] = location
    if content:
        item.headers["content-length"] = str(len(content))
    return item


def test_avatar_http_is_upgraded_and_safe_official_redirect_is_followed(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    replies = [
        response(302, location="https://mmbiz.qpic.cn/avatar/final"),
        response(200, content=png_bytes()),
    ]

    def fake_get(url: str, **_kwargs):
        calls.append(url)
        return replies.pop(0)

    monkeypatch.setattr(avatar_store, "user_avatar_dir", lambda _user_id: tmp_path)
    monkeypatch.setattr(avatar_store.requests, "get", fake_get)

    stored = avatar_store.download_wechat_avatar(
        "user-id", "http://thirdwx.qlogo.cn/avatar/source"
    )
    assert stored is not None and stored.endswith(".png")
    assert calls == [
        "https://thirdwx.qlogo.cn/avatar/source",
        "https://mmbiz.qpic.cn/avatar/final",
    ]
    assert (tmp_path / stored).is_file()


def test_avatar_redirect_to_untrusted_host_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        avatar_store.requests,
        "get",
        lambda *_args, **_kwargs: response(
            302, location="http://127.0.0.1/internal-avatar"
        ),
    )
    assert (
        avatar_store.download_wechat_avatar(
            "user-id", "https://thirdwx.qlogo.cn/avatar/source"
        )
        is None
    )
    assert avatar_store.download_wechat_avatar("user-id", "https://qlogo.cn:bad/x") is None