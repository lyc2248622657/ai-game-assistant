"""向量库运维：统计 / 脏数据清理 / 增量更新

对齐 RAG 岗硬要求（佰融资产 15-16K：向量库维护、增量更新、脏数据清理、
版本管理、RAG 召回指标、bad case 闭环；广西浩锋：知识库全链路）：
- list_collections / collection_stats：掌握各集合块数与来源分布（可观测）；
- delete_document / purge_orphans：脏数据清理（按文档删除、孤儿块回收）；
- rebuild_document：增量更新（先删旧块 → 重新分块向量化入库），
  用于文档修订后局部重建，避免全量重建。
"""
from pathlib import Path

from app.core.logging import get_logger
from app.rag import document_qa
from app.rag.vectorstore import get_vectorstore

logger = get_logger(__name__)


def list_collections() -> list[dict]:
    """列出全部向量集合及块数"""
    return get_vectorstore().list_collections()


def collection_stats(collection: str) -> dict:
    """集合统计：总量 / 按文档分布 / 按来源分布 / 孤儿文档块

    孤儿块 = metadatas 中 doc 指向的文件已不存在（documents 集合）。
    """
    data = get_vectorstore().get_all(collection)
    ids, metas = data["ids"], data["metadatas"]
    by_doc: dict[str, int] = {}
    by_source: dict[str, int] = {}
    orphan_ids: list[str] = []
    for i, meta in enumerate(metas):
        meta = meta or {}
        doc = str(meta.get("doc") or meta.get("game") or meta.get("title") or "未知")
        by_doc[doc] = by_doc.get(doc, 0) + 1
        source = str(meta.get("source") or "unknown")
        by_source[source] = by_source.get(source, 0) + 1
        if source == "document_qa" and doc != "未知":
            f = Path(document_qa.DOC_DIR) / f"{doc}.md"
            if not f.exists():
                orphan_ids.append(ids[i])
    return {
        "collection": collection,
        "total": len(ids),
        "by_doc": dict(sorted(by_doc.items(), key=lambda x: -x[1])),
        "by_source": dict(sorted(by_source.items(), key=lambda x: -x[1])),
        "orphan_docs": sorted({str(meta.get("doc")) for meta in metas if str(meta.get("source")) == "document_qa" and not (Path(document_qa.DOC_DIR) / f"{meta.get('doc')}.md").exists()}),
        "orphan_chunk_count": len(orphan_ids),
    }


def delete_document(collection: str, doc: str) -> dict:
    """按文档名删除其全部向量块（脏数据清理入口）"""
    n = get_vectorstore().delete_by_metadata(collection, {"doc": doc})
    logger.info("[vector_admin] 删除 %s/%s: %d 块", collection, doc, n)
    return {"collection": collection, "doc": doc, "deleted_chunks": n}


def purge_orphans(collection: str = document_qa.COLLECTION) -> dict:
    """清理孤儿块：documents 集合中源文件已不存在的块"""
    data = get_vectorstore().get_all(collection)
    ids, metas = data["ids"], data["metadatas"]
    orphan_ids = []
    for i, meta in enumerate(metas):
        meta = meta or {}
        if meta.get("source") != "document_qa":
            continue
        doc = str(meta.get("doc") or "")
        if not doc:
            continue
        if not (Path(document_qa.DOC_DIR) / f"{doc}.md").exists():
            orphan_ids.append(ids[i])
    if orphan_ids:
        get_vectorstore().get_collection(collection).delete(ids=orphan_ids)
    logger.info("[vector_admin] 清理孤儿块 %s: %d", collection, len(orphan_ids))
    return {"collection": collection, "purged_chunks": len(orphan_ids)}


def rebuild_document(doc: str, content: str | None = None) -> dict:
    """增量重建：先删该文档旧块 → 重新分块向量化入库（文档修订后局部重建）

    content 为空时读取 data/documents/{doc}.md 现有内容；
    文档不存在且无 content 时返回错误信息（不抛异常，供 API 友好返回）。
    """
    store = get_vectorstore()
    deleted = store.delete_by_metadata(document_qa.COLLECTION, {"doc": doc})
    if content is None:
        path = Path(document_qa.DOC_DIR) / f"{doc}.md"
        if not path.exists():
            logger.warning("[vector_admin] 重建失败：文档不存在 %s", path)
            return {"ok": False, "message": f"文档 {doc} 不存在（无内容可重建）", "deleted_chunks": deleted}
        content = path.read_text(encoding="utf-8")
    result = document_qa.ingest_document(doc, content)
    result["ok"] = True
    result["deleted_chunks"] = deleted
    logger.info("[vector_admin] 重建 %s: 删 %d 块 / 入 %d 块", doc, deleted, result["chunks"])
    return result
