from __future__ import annotations

import base64
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image as PillowImage

from app.main import app


def png_bytes() -> bytes:
    output = BytesIO()
    PillowImage.new("RGB", (2, 2), color="white").save(output, format="PNG")
    return output.getvalue()


def test_unconfigured_health_settings_and_atomic_image_upload() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["configured"] is False

        saved = client.put(
            "/api/settings",
            json={
                "user_token": "2_api_test_token",
                "heartbeat_interval": 60,
                "worker_enabled": False,
            },
        )
        assert saved.status_code == 200
        assert "2_api_test_token" not in saved.text
        assert saved.json()["has_user_token"] is True

        uploaded = client.post(
            "/api/images",
            data={"category": "library"},
            files=[("files", ("camera.png", png_bytes(), "image/png"))],
        )
        assert uploaded.status_code == 201
        image_id = uploaded.json()[0]["id"]

        configured = client.put(
            "/api/settings",
            json={
                "image_mode": "single",
                "selected_image_id": image_id,
                "worker_enabled": False,
            },
        )
        assert configured.status_code == 200
        assert configured.json()["configured"] is True

        before = client.get("/api/images", params={"category": "library"}).json()["total"]
        rejected = client.post(
            "/api/images",
            data={"category": "library"},
            files=[
                ("files", ("valid.png", png_bytes(), "image/png")),
                ("files", ("forged.jpg", png_bytes(), "image/jpeg")),
            ],
        )
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] == "INVALID_IMAGE"
        after = client.get("/api/images", params={"category": "library"}).json()["total"]
        assert after == before

        in_use = client.delete(f"/api/images/{image_id}")
        assert in_use.status_code == 409
        assert in_use.json()["detail"]["code"] == "IMAGE_IN_USE"

        missing_api = client.get("/api/not-a-real-endpoint")
        assert missing_api.status_code == 404
        assert missing_api.json()["detail"]["code"] == "NOT_FOUND"

    # 重新进入 lifespan，模拟容器重启后复用同一个 /data 数据库与图片目录。
    with TestClient(app) as restarted:
        persisted = restarted.get("/api/settings")
        assert persisted.status_code == 200
        assert persisted.json()["configured"] is True
        assert persisted.json()["selected_image_id"] == image_id
        assert restarted.get(f"/api/images/{image_id}").status_code == 200


def test_settings_accepts_full_authorization_and_rejects_malformed_without_echo() -> None:
    token = "2_api_authorization_token"
    authorization = base64.b64encode(
        f"1773238142:nonceForWebTest1:{'b' * 32}:{token}".encode()
    ).decode()
    invalid_authorization = base64.b64encode(
        b"1773238142:sensitive-marker:not-a-signature:2_hidden"
    ).decode()

    with TestClient(app) as client:
        saved = client.put("/api/settings", json={"user_token": authorization})
        assert saved.status_code == 200
        assert authorization not in saved.text
        assert token not in saved.text
        assert saved.json()["has_user_token"] is True

        rejected = client.put(
            "/api/settings",
            json={"user_token": invalid_authorization},
        )
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] == "VALIDATION_ERROR"
        assert invalid_authorization not in rejected.text
        assert "sensitive-marker" not in rejected.text
        assert "2_hidden" not in rejected.text
