"""企业文档问答（Document QA）

独立于游戏知识库的通用文档问答：
- ingest：保存文档（md/txt）到 data/documents/，按段落分块后向量化入库（Chroma「documents」集合）；
- ask：向量检索 + 关键词过滤 → 组装带引用上下文 → LLM 生成回答（引用 title+content 输出，降低幻觉）。

设计意图：同一套 RAG 能力复用到企业文档问答场景（制度/产品手册/知识库），
验证检索能力脱离游戏领域的可迁移性。
"""
import re
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.rag.embedding import get_embedding
from app.rag.vectorstore import get_vectorstore

logger = get_logger(__name__)

DOC_DIR = Path(settings.documents_dir)
COLLECTION = "documents"
_CHUNK_MAX = 600
_CHUNK_OVERLAP = 80


def _chunk(text: str) -> list[str]:
    """按段落分块：保留段落边界，长段按 _CHUNK_MAX 切分并带 _CHUNK_OVERLAP 重叠"""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    for p in paras:
        if len(p) <= _CHUNK_MAX:
            chunks.append(p)
            continue
        start = 0
        while start < len(p):
            end = min(start + _CHUNK_MAX, len(p))
            chunks.append(p[start:end])
            if end >= len(p):
                break
            start = end - _CHUNK_OVERLAP
    return chunks


def _doc_id(name: str, idx: int) -> str:
    return f"{name}::{idx}"


def list_documents() -> list[dict]:
    """已入库文档清单（按文件）"""
    out = []
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    for p in sorted(DOC_DIR.glob("*.md")):
        out.append({"name": p.stem, "path": str(p), "size": p.stat().st_size})
    return out


def ingest_document(name: str, content: str) -> dict:
    """保存文档 + 分块向量化入库；返回入库块数"""
    name = re.sub(r"[^\w\u4e00-\u9fa5-]", "_", name)[:60]
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    path = DOC_DIR / f"{name}.md"
    path.write_text(content, encoding="utf-8")

    chunks = _chunk(content)
    emb = get_embedding()
    store = get_vectorstore()
    ids = [_doc_id(name, i) for i in range(len(chunks))]
    metas = [{"source": "document_qa", "doc": name, "title": name} for _ in chunks]
    store.upsert(COLLECTION, ids, chunks, metas, emb.encode(chunks))
    logger.info("[docqa] ingest %s: %d 块", name, len(chunks))
    return {"name": name, "chunks": len(chunks), "path": str(path)}


def _search(question: str, top_k: int = 4) -> list[dict]:
    """向量检索 documents 集合 + 关键词/全文兜底；返回 [{doc_id, title, content, score}]"""
    try:
        q_vec = get_embedding().encode([question])[0]
        hits = get_vectorstore().query(COLLECTION, q_vec, top_k=top_k)
        out = []
        for r in hits:
            score = 1.0 - r["distance"]
            if score < 0.25:
                continue
            out.append({
                "doc_id": r["id"],
                "title": (r["metadata"] or {}).get("title", r["id"]),
                "content": r["text"],
                "score": round(score, 4),
            })
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("[docqa] 向量检索不可用，全文兜底: %s", e)
        hits: list[dict] = []
        for p in DOC_DIR.glob("*.md"):
            text = p.read_text(encoding="utf-8")
            if question[:6] in text:
                hits.append({"doc_id": p.stem, "title": p.stem, "content": text[:600], "score": 0.5})
        return hits[:top_k]


def ask(question: str, top_k: int = 4) -> dict:
    """文档问答：检索 → 引用上下文 → LLM 回答（附引用，失败降级为引用摘要）"""
    docs = _search(question, top_k=top_k)
    if not docs:
        return {"answer": "资料库中未检索到与问题相关的内容。", "citations": [], "retrieved": 0}
    context = "\n\n".join(f"[{i+1}] {d['content']}" for i, d in enumerate(docs))
    citations = [
        {"title": d["title"], "content": d["content"][:1200], "doc_id": d["doc_id"]}
        for d in docs
    ]
    try:
        from app.agents.llm import get_chat_model

        resp = get_chat_model().invoke(
            "你是企业知识库问答助手。严格依据下方资料回答，资料未覆盖的内容明确说明"
            "『资料未收录』，不得编造。回答末尾用[1][2]标注引用来源。\n\n资料：\n" + context
            + "\n\n问题：" + question
        )
        answer = (resp.content or "").strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("[docqa] LLM 回答失败，降级为引用摘要: %s", e)
        answer = "检索到以下相关资料（LLM 暂不可用）：\n" + "\n".join(
            f"[{i+1}] {d['title']}: {d['content'][:100]}" for i, d in enumerate(docs)
        )
    return {"answer": answer, "citations": citations, "retrieved": len(docs)}
