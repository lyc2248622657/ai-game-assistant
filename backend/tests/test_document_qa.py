"""企业文档问答（FDE 演示）单测：分块 / 入库参数 / 检索兜底 / LLM 降级"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag import document_qa as dqa  # noqa: E402


def test_chunk_single_paragraph_kept():
    assert dqa._chunk("只有一段内容。") == ["只有一段内容。"]


def test_chunk_splits_long_paragraph_with_overlap():
    long = "甲" * 1300
    chunks = dqa._chunk(long)
    assert len(chunks) >= 2
    assert all(len(c) <= dqa._CHUNK_MAX for c in chunks)
    # 相邻块有重叠
    assert chunks[0][-dqa._CHUNK_OVERLAP:] == chunks[1][:dqa._CHUNK_OVERLAP]


def test_chunk_preserves_paragraph_boundaries():
    text = "第一段内容。\n\n第二段内容，第二段很长" + "乙" * 700
    chunks = dqa._chunk(text)
    assert any("第一段内容" in c for c in chunks)
    assert any("第二段内容" in c for c in chunks)


def test_ingest_upserts_chunks(monkeypatch, tmp_path):
    """入库：分块 → upsert 到 documents 集合（mock 向量与存储，不碰真实库）"""
    captured = {}

    class FakeEmb:
        def encode(self, texts):
            class V:
                def tolist(self):
                    return [[0.1] * 8] * len(texts)

            return V()

    monkeypatch.setattr(dqa, "get_embedding", lambda: FakeEmb())

    class FakeStore:
        def upsert(self, collection, ids, texts, metas, embeddings):
            captured.update(collection=collection, ids=ids, n=len(texts))

    monkeypatch.setattr(dqa, "get_vectorstore", lambda: FakeStore())
    monkeypatch.setattr(dqa, "DOC_DIR", tmp_path)
    r = dqa.ingest_document("测试制度", "第一条：请假需审批。\n\n第二条：报销需发票。" * 3)
    assert captured["collection"] == "documents"
    assert captured["n"] == r["chunks"]
    assert (tmp_path / "测试制度.md").exists()


def test_ask_llm_fail_falls_back_to_summary(monkeypatch):
    """LLM 不可用 → 降级为引用摘要，不抛异常"""
    docs = [{"doc_id": "d1", "title": "请假制度", "content": "病假超过 3 天需诊断证明。", "score": 0.8}]
    monkeypatch.setattr(dqa, "_search", lambda q, top_k=4: docs)

    class Boom:
        def invoke(self, *a, **k):
            raise RuntimeError("LLM 超时")

    monkeypatch.setattr("app.agents.llm.get_chat_model", lambda: Boom())
    r = dqa.ask("病假需要什么证明？")
    assert "请假制度" in r["answer"]  # 引用摘要兜底
    assert r["citations"][0]["title"] == "请假制度"
    assert r["retrieved"] == 1


def test_ask_no_docs_returns_honest_empty(monkeypatch):
    monkeypatch.setattr(dqa, "_search", lambda q, top_k=4: [])
    r = dqa.ask("薪资结构是什么？")
    assert "未检索到" in r["answer"]
    assert r["citations"] == []


def test_search_vector_fallback_on_failure(monkeypatch, tmp_path):
    """向量检索失败 → 全文兜底命中包含关键词的文档"""
    (tmp_path / "制度.md").write_text("年假：入职满一年享有 5 天带薪年假。", encoding="utf-8")

    def boom(query, top_k):
        raise RuntimeError("向量不可用")

    monkeypatch.setattr(dqa, "get_embedding", lambda: object())
    monkeypatch.setattr(dqa, "get_vectorstore", lambda: object())
    monkeypatch.setattr(dqa, "DOC_DIR", tmp_path)
    # 直接调全文兜底分支：get_vectorstore().query 抛异常
    monkeypatch.setattr(
        "app.rag.vectorstore.VectorStore.query", lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
    )
    hits = dqa._search("年假")
    assert hits and hits[0]["title"] == "制度"
