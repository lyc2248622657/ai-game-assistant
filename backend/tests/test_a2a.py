"""A2A 多智能体协同单测：分解 / 派发 / 汇总 / 全流程（mock LLM，不碰真实 API）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from app.agents import a2a  # noqa: E402


class _FakeResp:
    def __init__(self, text):
        self.content = text


# ---------- 分解 ----------


def test_decompose_llm(monkeypatch):
    """LLM 返回 JSON 数组 → 过滤非法智能体"""
    calls = []

    class _FakeModel:
        def invoke(self, messages):
            calls.append(messages)
            return _FakeResp('[{"agent": "doc_agent", "task": "文档问答", "args": {"question": "病假"}}, {"agent": "nope", "task": "x", "args": {}}]')

    monkeypatch.setattr("app.agents.llm.get_chat_model", lambda: _FakeModel())
    runs = a2a.decompose("病假规定？", use_llm=True)
    assert len(runs) == 1
    assert runs[0]["agent"] == "doc_agent"


def test_decompose_llm_failure_falls_back(monkeypatch):
    """LLM 抛异常 → 关键词兜底仍能分解"""
    def boom():
        raise RuntimeError("no key")

    monkeypatch.setattr("app.agents.llm.get_chat_model", boom)
    runs = a2a.decompose("统计文档库有多少块", use_llm=True)
    assert any(r["agent"] == "vector_agent" for r in runs)


def test_keyword_decompose_doc_and_game():
    runs = a2a._keyword_decompose("能天使强度如何？病假超过几天要开证明")
    agents = {r["agent"] for r in runs}
    assert "game_agent" in agents
    assert "doc_agent" in agents


# ---------- 派发 ----------


def test_dispatch_game_agent(monkeypatch):
    """game_agent：实体查询 + 知识检索"""
    captured = {}

    class _FakeTool:
        def run(self, args, ctx):
            captured["args"] = args
            return {"found": True, "entity": {"name": "能天使", "rarity": 6}}

    monkeypatch.setattr(a2a, "QueryGameEntityTool", lambda: _FakeTool())
    monkeypatch.setattr(
        a2a, "hybrid_retrieve",
        lambda game, query, top_k=4: [{"title": "能天使", "content": "狙击速射手"}],
    )
    out = a2a.dispatch([{"agent": "game_agent", "task": "t", "args": {"game": "arknights", "type": "character", "name": "能天使", "query": "能天使 狙击"}}])
    r = out[0]["result"]
    assert r["ok"] is True
    assert r["entity"]["entity"]["name"] == "能天使"
    assert len(r["retrieval"]) == 1


def test_dispatch_doc_agent(monkeypatch):
    monkeypatch.setattr(a2a.document_qa, "ask", lambda q, top_k=4: {"answer": "病假超3天需证明。[1]", "retrieved": 1})
    out = a2a.dispatch([{"agent": "doc_agent", "task": "t", "args": {"question": "病假"}}])
    assert out[0]["result"]["ok"] is True
    assert "[1]" in out[0]["result"]["answer"]


def test_dispatch_vector_agent(monkeypatch):
    monkeypatch.setattr(a2a.vector_admin, "collection_stats", lambda c: {"collection": c, "total": 30, "orphan_chunk_count": 0, "by_doc": {"d": 30}})
    out = a2a.dispatch([{"agent": "vector_agent", "task": "t", "args": {"collection": "documents"}}])
    assert out[0]["result"]["stats"]["total"] == 30


def test_dispatch_unknown_agent_degrades():
    """未知智能体 → 单点降级标记 error，不抛异常"""
    out = a2a.dispatch([{"agent": "ghost", "task": "t", "args": {}}])
    assert out[0]["result"]["ok"] is False
    assert "未知智能体" in out[0]["result"]["message"]


# ---------- 汇总 ----------


def test_synthesize_llm(monkeypatch):
    class _FakeModel:
        def invoke(self, messages):
            return _FakeResp("能天使是6星狙击。[game_agent] 病假超3天需证明。[doc_agent]")

    monkeypatch.setattr("app.agents.llm.get_chat_model", lambda: _FakeModel())
    answer = a2a.synthesize("q", [{"index": 1, "agent": "game_agent", "task": "t", "result": {"ok": True, "entity": {"found": True, "entity": {"name": "能天使", "rarity": 6}}}}], use_llm=True)
    assert "[game_agent]" in answer


def test_synthesize_fallback():
    """无 LLM → 结构化拼接各智能体结果"""
    answer = a2a.synthesize(
        "q",
        [
            {"index": 1, "agent": "game_agent", "task": "t", "result": {"ok": True, "entity": {"found": True, "entity": {"name": "能天使", "rarity": 6}}}},
            {"index": 2, "agent": "doc_agent", "task": "t", "result": {"ok": True, "answer": "病假超3天需证明", "retrieved": 1}},
        ],
        use_llm=False,
    )
    assert "[game_agent]" in answer and "[doc_agent]" in answer


# ---------- 全流程 ----------


def test_run_full(monkeypatch):
    """run：分解 → 派发 → 汇总 闭环"""
    monkeypatch.setattr("app.agents.llm.get_chat_model", lambda: None)  # 触发 decompose/synthesize 兜底
    out = a2a.run("统计文档库多少块", use_llm=True)
    assert out["subtasks"] and any(r["agent"] == "vector_agent" for r in out["subtasks"])
    assert out["answer"]
