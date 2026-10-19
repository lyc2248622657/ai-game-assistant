"""接口鉴权测试：令牌校验、豁免路径、限流、轮换限制。

约定（见 `app/core/auth.py`）：
  - 非回环来源访问 `/api/*` 与 `/uploads/*` 必须携带令牌；
  - `/api/health`、`/api/auth/status` 豁免；
  - 令牌可用 `Authorization: Bearer`、`X-API-Token` 或 `?token=` 传递；
  - 失败过多返回 429；令牌轮换只允许回环来源。
"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

TOKEN = "test-token-please-change"


@pytest.fixture()
def client():
    from app.core import auth
    from app.main import app

    auth.reset_failures("testclient")
    with TestClient(app) as c:
        yield c


def test_health_is_exempt(client):
    assert client.get("/api/health").status_code == 200


def test_api_without_token_is_401(client):
    resp = client.get("/api/games")
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == 10008
    assert "令牌" in body["message"]
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_wrong_token_is_401(client):
    resp = client.get("/api/games", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


@pytest.mark.parametrize("headers", [
    {"Authorization": f"Bearer {TOKEN}"},
    {"X-API-Token": TOKEN},
])
def test_valid_token_header_variants(client, headers):
    resp = client.get("/api/games", headers=headers)
    assert resp.status_code == 200


def test_token_via_query_param(client):
    """`?token=` 是给 <img src="/uploads/..."> 这类无法带请求头的场景用的"""
    resp = client.get("/api/games", params={"token": TOKEN})
    assert resp.status_code == 200


def test_uploads_requires_token(client):
    assert client.get("/uploads/not-exist.png").status_code == 401
    # 带令牌时不再是 401（文件不存在会是 404）
    resp = client.get("/uploads/not-exist.png", params={"token": TOKEN})
    assert resp.status_code == 404


def test_static_shell_stays_open(client):
    """前端静态资源必须开放，否则远端连"输入令牌"的页面都加载不出来"""
    resp = client.get("/")
    assert resp.status_code != 401


def test_auth_status_is_exempt_and_never_leaks_remote_token(client):
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_required"] is True
    assert body["authorized"] is False
    # TestClient 来源不是回环 → 不允许回传明文令牌
    assert body["token"] is None


def test_auth_status_authorized_with_token(client):
    body = client.get("/api/auth/status", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert body["authorized"] is True


def test_rotate_rejected_for_non_loopback(client):
    resp = client.post("/api/auth/rotate", headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 403


def test_fail_rate_limit(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "auth_fail_limit", 2)
    for _ in range(2):
        assert client.get("/api/games").status_code == 401
    resp = client.get("/api/games")
    assert resp.status_code == 429
    assert resp.json()["code"] == 10008


# ---------- 回环信任的边界：直连可以，经反代不行 ----------
@pytest.fixture()
def loopback_client(monkeypatch):
    """模拟"来源是 127.0.0.1"的客户端，并开启回环免令牌"""
    from app.core import auth
    from app.core.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "trust_loopback", True)
    auth.reset_failures("127.0.0.1")
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        yield c


def test_loopback_direct_request_is_free(loopback_client):
    assert loopback_client.get("/api/games").status_code == 200


def test_loopback_behind_proxy_still_needs_token(loopback_client):
    """带 X-Forwarded-For = 经过反代；反代同机时 TCP 对端也是 127.0.0.1，
    若不额外判断就会把公网请求当成"本机请求"放行。"""
    resp = loopback_client.get("/api/games", headers={"X-Forwarded-For": "203.0.113.9"})
    assert resp.status_code == 401
    ok = loopback_client.get(
        "/api/games",
        headers={"X-Forwarded-For": "203.0.113.9", "Authorization": f"Bearer {TOKEN}"},
    )
    assert ok.status_code == 200
