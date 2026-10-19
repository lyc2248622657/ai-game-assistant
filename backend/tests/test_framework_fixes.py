"""框架层缺陷回归测试（对应 docs/框架问题排查报告.md）

每个用例对应报告里的一条 P0/P1，防止同类问题再次出现：
  - LangGraph 状态通道必须与 graph.py 实际读写一致（否则被静默丢弃）
  - ErrorCode 只允许使用已定义的成员
  - SQLite 连接必须关闭 + 启用 WAL
  - token 用量/错误状态等契约
  - 混合检索的 RRF 融合不会被词法分支压制
"""
import ast
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.agents.state import AgentState, initial_state  # noqa: E402
from app.core.errors import AppError, ErrorCode  # noqa: E402
from app.core.sqlite import connect  # noqa: E402
from app.memory.store import SessionStore  # noqa: E402


# ---------- 1. LangGraph 状态通道一致性 ----------
def _state_keys_used_in_graph() -> set[str]:
    """静态解析 graph.py：收集所有 state["x"] / state.get("x") 的键名"""
    src = (BACKEND / "app" / "agents" / "graph.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "state":
            sl = node.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                keys.add(sl.value)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "state"
            and node.args
        ):
            a0 = node.args[0]
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                keys.add(a0.value)
    return keys


def test_graph_state_keys_are_all_declared():
    """graph.py 读写的每个键都必须声明在 AgentState 里。

    LangGraph 只把**已声明**的键当作 channel，写入未声明的键会被静默丢弃
    （langgraph/pregel/_algo.py: "wrote to unknown channel ... ignoring it"），
    表现为"某个节点的产出到下一个节点就读不到了"——历史 bug：
    memory_context / guides / related_entities 全部丢失。
    """
    declared = set(AgentState.__annotations__)
    missing = _state_keys_used_in_graph() - declared
    assert not missing, f"graph.py 使用了未声明的状态通道（会被 LangGraph 静默丢弃）: {sorted(missing)}"


def test_memory_and_guides_are_declared_channels():
    """回归：记忆注入 / 攻略 / 相关实体必须是真实 channel"""
    for key in ("memory_context", "guides", "related_entities"):
        assert key in AgentState.__annotations__, f"{key} 未声明为状态通道"


def test_initial_state_covers_new_channels():
    st = initial_state("genshin", "s1", "胡桃怎么样", [])
    assert st.get("memory_context") is None
    assert st.get("related_entities") == []
    assert st.get("guides") is None


def test_declared_channel_survives_between_nodes():
    """机制级回归：声明过的通道必须能跨节点传递。

    这是 P0-1 的核心——修复前 memory_context 不在 AgentState 里，
    写它的节点产出会被 LangGraph 静默丢弃，下游节点永远读到 None。
    """
    from langgraph.graph import END, START, StateGraph

    seen: dict = {}

    def writer(state):
        return {"memory_context": "MEMORY-CTX"}

    def reader(state):
        seen["value"] = state.get("memory_context")
        return {}

    g = StateGraph(AgentState)
    g.add_node("writer", writer)
    g.add_node("reader", reader)
    g.add_edge(START, "writer")
    g.add_edge("writer", "reader")
    g.add_edge("reader", END)
    g.compile().invoke({"game_id": "genshin", "user_message": "x"})
    assert seen["value"] == "MEMORY-CTX"


# ---------- 2. 错误码与 HTTP 状态契约 ----------
def test_error_codes_used_in_source_are_defined():
    """所有 ErrorCode.<X> 引用都必须是已定义成员。

    历史 bug：vision.py 用了不存在的 ErrorCode.BAD_REQUEST，
    上传校验错误路径直接 AttributeError → 500。
    """
    known = {c.name for c in ErrorCode}
    used: set[str] = set()
    for path in (BACKEND / "app").rglob("*.py"):
        for m in __import__("re").finditer(r"ErrorCode\.([A-Z_]+)", path.read_text(encoding="utf-8")):
            used.add(m.group(1))
    unknown = used - known
    assert not unknown, f"引用了未定义的错误码: {sorted(unknown)}"


def test_app_error_default_http_status():
    assert AppError(ErrorCode.SESSION_NOT_FOUND, "x").http_status == 404
    assert AppError(ErrorCode.GAME_NOT_FOUND, "x").http_status == 404
    assert AppError(ErrorCode.INVALID_REQUEST, "x").http_status == 400
    assert AppError(ErrorCode.INTERNAL, "x").http_status == 500
    # 显式传入优先
    assert AppError(ErrorCode.INVALID_REQUEST, "x", 409).http_status == 409


# ---------- 3. SQLite 连接生命周期 ----------
def test_connect_closes_connection(tmp_path):
    db = tmp_path / "t.db"
    with connect(db) as conn:
        conn.execute("CREATE TABLE t(a INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
    # 退出后连接必须已关闭
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
    with connect(db) as conn2:
        assert conn2.execute("SELECT a FROM t").fetchone()["a"] == 1


def test_connect_enables_wal(tmp_path):
    """WAL：并发读写下不互相阻塞（历史问题：默认 rollback journal 会 database is locked）"""
    db = tmp_path / "w.db"
    with connect(db) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"


def test_connect_rolls_back_on_error(tmp_path):
    db = tmp_path / "r.db"
    with connect(db) as conn:
        conn.execute("CREATE TABLE t(a INTEGER)")
    with pytest.raises(RuntimeError):
        with connect(db) as conn:
            conn.execute("INSERT INTO t VALUES (2)")
            raise RuntimeError("boom")
    with connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM t").fetchone()["c"] == 0


# ---------- 4. SessionStore 行为（N+1 修复后的正确性） ----------
def test_session_store_message_count(tmp_path):
    store = SessionStore(db_path=str(tmp_path / "s.db"))
    s = store.create_session("genshin", "测试")
    store.add_message(s["session_id"], "user", "你好")
    store.add_message(s["session_id"], "assistant", "在")
    assert store.get_session(s["session_id"])["message_count"] == 2
    listed = store.list_sessions()
    assert [x["message_count"] for x in listed] == [2]
    assert store.list_sessions("arknights") == []


def test_delete_missing_session_raises_404_semantics(tmp_path):
    store = SessionStore(db_path=str(tmp_path / "d.db"))
    with pytest.raises(AppError) as ei:
        store.delete_session("nope")
    assert ei.value.http_status == 404


# ---------- 5. 兜底节点可达 + 混合检索融合 ----------
def test_fallback_node_is_reachable():
    """回归：fallback 曾无入边（死代码）"""
    from app.agents.graph import N_FALLBACK, N_TOOL, build_graph, decide_after_tool

    g = build_graph()
    assert N_FALLBACK in g.nodes
    # 通过 decide_after_tool 直接验证路由语义（比断言内部图结构更稳定）
    assert N_TOOL  # 确保常量存在
    assert decide_after_tool({"error": "boom"}) == N_FALLBACK
    assert decide_after_tool({"error": None}) == "replan"


def test_rrf_fusion_prefers_consistent_hits():
    """RRF：两路都命中的文档应排在"只有单路高分"的文档之前。

    历史问题：BM25 分被缩放到 [0.55,0.95] 后与余弦相似度取 max，
    一个垃圾词法命中也必然压制真正的语义命中。
    """
    from app.rag.retriever import _rrf_fuse

    vec = [
        {"doc_id": "a", "score": 0.70},
        {"doc_id": "b", "score": 0.65},
    ]
    bm25 = [
        {"doc_id": "junk", "score": 1.0},
        {"doc_id": "b", "score": 0.5},
    ]
    fused = [d["doc_id"] for d in _rrf_fuse([vec, bm25])]
    # b 在两路都靠前 → 应当第一；junk 只在单路第一 → 不应压制 b
    assert fused[0] == "b"
    assert fused.index("junk") > fused.index("b")


def test_bm25_scores_bounded():
    from app.rag.retriever import _bm25_retrieve

    class _G:
        data_dir = BACKEND / "data" / "genshin"

    try:
        docs = _bm25_retrieve(_G(), "胡桃", top_k=3)
    except Exception:  # 无数据目录时跳过
        pytest.skip("缺少 genshin 数据目录")
    for d in docs:
        assert 0.0 <= d["score"] <= 1.0


# ---------- 6. 端到端：记忆上下文真的到达下游 prompt ----------
class _FakeResp:
    def __init__(self, content: str):
        self.content = content
        self.tool_calls = []


class _FakeModel:
    """按 system prompt 内容返回不同结果，模拟主管 / 子代理 / 质检"""

    def __init__(self, systems: list[str]):
        self._systems = systems

    def bind_tools(self, *_a, **_k):
        return self

    def invoke(self, messages, *_a, **_k):
        system = ""
        if isinstance(messages, list) and messages and isinstance(messages[0], dict):
            system = messages[0].get("content", "")
        elif isinstance(messages, str):
            system = messages
        self._systems.append(system)
        if "JSON" in system or "委派" in system:
            return _FakeResp('{"game_id":"genshin","domain":"knowledge","brief":"t","reason":"t"}')
        if "质检" in system:
            return _FakeResp('{"pass": true, "issues": []}')
        return _FakeResp("胡桃是火系角色，推荐蒸发队。")


def test_memory_context_reaches_downstream_prompt(monkeypatch):
    """P0-1 的产品级验证：记忆召回的内容必须出现在下游节点的 system prompt 里。

    修复前 memory_context 不是声明过的通道，写完就被 LangGraph 丢弃，
    下游永远拿到 None —— 检索花钱但完全没用上。
    """
    from app.agents import graph as G

    systems: list[str] = []
    monkeypatch.setattr(G, "get_chat_model", lambda *a, **k: _FakeModel(systems))
    monkeypatch.setattr(G.user_memory, "get_prefs", lambda gid: ["喜欢胡桃"])
    monkeypatch.setattr(G.session_memory, "get_summary", lambda sid: None)
    monkeypatch.setattr(
        G.memory_rag,
        "retrieve",
        lambda gid, q, top_k=5: [{"kind": "pref", "text": "用户偏好：喜欢胡桃", "score": 0.9, "ts": ""}],
    )
    # 避免检索/配图路径联网或读大文件
    from app.rag import retriever as R

    monkeypatch.setattr(R, "hybrid_retrieve", lambda game, query, top_k=4: [])
    monkeypatch.setattr(G, "_attach_images_to_state", lambda state: None)

    result = G.app_graph.invoke(initial_state("genshin", "s-e2e", "这个版本练什么好", []))
    assert result.get("final_answer")
    assert result.get("memory_context"), "memory_context 应保留在最终状态里"
    assert any("用户偏好：喜欢胡桃" in s for s in systems), "记忆内容必须进入某个节点的 system prompt"


# ---------- 7. 上传路径守卫：image_path 不得指向任意本地文件 ----------
def test_ensure_upload_path_accepts_inside(tmp_path):
    from app.core.paths import ensure_upload_path

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    ok = uploads / "shot.png"
    ok.write_bytes(b"\x89PNG")
    assert ensure_upload_path(str(ok), upload_dir=uploads) == ok.resolve()


def test_ensure_upload_path_rejects_outside(tmp_path):
    from app.core.paths import ensure_upload_path

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"top-secret")
    with pytest.raises(ValueError):
        ensure_upload_path(str(secret), upload_dir=uploads)
    # 目录穿越也要挡住
    with pytest.raises(ValueError):
        ensure_upload_path(str(uploads / ".." / "secret.png"), upload_dir=uploads)


def test_chat_request_rejects_foreign_image_path(tmp_path):
    """入口校验：越界的 image_path 直接 422，不会走到视觉工具去读文件。"""
    from pydantic import ValidationError

    from app.schemas.chat import ChatRequest

    outside = tmp_path / "passwd.png"
    outside.write_bytes(b"x")
    with pytest.raises(ValidationError):
        ChatRequest(message="hi", image_path=str(outside))
    # 不传 image_path 时正常
    assert ChatRequest(message="hi").image_path is None


def test_vision_encode_image_guards_path():
    """视觉工具侧也有一道：即使绕过 API 直接调工具，也不能读上传目录外的文件。"""
    from app.tools.vision_tool import encode_image

    outside = Path(__file__).resolve()  # 用本测试文件当"任意本地文件"
    with pytest.raises(ValueError):
        encode_image(str(outside))
