"""接口契约测试：用 TestClient 走真实 HTTP 层，锁定错误响应形状与关键状态码。

覆盖本轮修复：
  - 统一错误契约 `{code, message}`（业务异常 / 校验失败 / 未知路由 / 框架 404）
  - `SESSION_NOT_FOUND` / `GAME_NOT_FOUND` 返回 404 而非 400
  - 上传格式校验返回 400（`ErrorCode.BAD_REQUEST` 不存在导致的 500 回归）
  - 养成计划删除必须带 session_id 且校验归属
"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def client():
    """带访问令牌的客户端（conftest 已设 API_TOKEN / 关闭回环免校验）"""
    from app.main import app

    with TestClient(app) as c:
        c.headers.update({"Authorization": "Bearer test-token-please-change"})
        yield c


def _json(resp):
    assert resp.headers.get("content-type", "").startswith("application/json"), resp.text[:200]
    return resp.json()


def test_health(client):
    body = _json(client.get("/api/health"))
    assert body["status"] == "ok"


def test_games_shape(client):
    body = _json(client.get("/api/games"))
    assert isinstance(body["games"], list)
    assert all({"game_id", "name", "enabled"} <= set(g) for g in body["games"])


def test_unknown_api_returns_json_404(client):
    """未知 /api 路径不能被前端静态挂载吞成 index.html"""
    resp = client.get("/api/definitely-not-exist")
    assert resp.status_code == 404
    body = _json(resp)
    assert set(body) == {"code", "message"}


def test_unknown_game_404(client):
    resp = client.post("/api/sessions", json={"game_id": "not-a-game"})
    assert resp.status_code == 404
    assert _json(resp)["code"] == 10002


def test_missing_session_404(client):
    resp = client.get("/api/sessions/nope/messages")
    assert resp.status_code == 404
    assert _json(resp)["code"] == 10003


def test_validation_error_shape(client):
    resp = client.post("/api/chat", json={"message": ""})
    assert resp.status_code == 422
    assert set(_json(resp)) == {"code", "message"}


def test_session_crud(client):
    created = _json(client.post("/api/sessions", json={"game_id": "genshin"}))
    sid = created["session_id"]
    assert created["message_count"] == 0

    renamed = _json(client.put(f"/api/sessions/{sid}", json={"title": "回归测试会话"}))
    assert renamed["title"] == "回归测试会话"

    assert _json(client.get(f"/api/sessions/{sid}/messages"))["messages"] == []
    assert _json(client.delete(f"/api/sessions/{sid}"))["ok"] is True
    assert client.get(f"/api/sessions/{sid}/messages").status_code == 404


def test_blank_title_rejected(client):
    sid = _json(client.post("/api/sessions", json={"game_id": "genshin"}))["session_id"]
    resp = client.put(f"/api/sessions/{sid}", json={"title": "   "})
    assert resp.status_code == 400
    assert _json(resp)["code"] == 10001


def test_upload_rejects_bad_extension(client):
    resp = client.post("/api/vision/upload", files={"file": ("a.exe", b"MZ", "application/octet-stream")})
    assert resp.status_code == 400
    assert _json(resp)["code"] == 10001


def test_upload_accepts_png(client):
    resp = client.post("/api/vision/upload", files={"file": ("a.png", b"\x89PNG\r\n\x1a\n", "image/png")})
    assert resp.status_code == 200
    body = _json(resp)
    assert body["ok"] is True and body["image_url"].endswith(".png")


def test_chat_rejects_image_path_outside_uploads(client):
    """image_path 越界时在入口就 422，不会走到视觉工具去读任意本地文件"""
    resp = client.post("/api/chat", json={"message": "hi", "image_path": "C:/Windows/win.ini"})
    assert resp.status_code == 422
    assert set(_json(resp)) == {"code", "message"}


def test_key_status_never_leaks_plaintext(client):
    body = _json(client.get("/api/settings/key"))
    assert "configured" in body
    assert "api_key" not in body


def test_plan_delete_requires_session_and_ownership(client):
    from app.tools.build_plan import plan_store

    pid = plan_store.save("sess-owner", "genshin", "胡桃", "90", {"materials": []})

    # 缺 session_id → 422（参数校验）
    assert client.delete(f"/api/plans/{pid}").status_code == 422
    # 归属不符 → 404
    assert client.delete(f"/api/plans/{pid}", params={"session_id": "sess-other"}).status_code == 404
    # 正确归属 → 200
    assert _json(client.delete(f"/api/plans/{pid}", params={"session_id": "sess-owner"}))["ok"] is True
    assert plan_store.list_by_session("sess-owner") == []
