"""向量库运维 API：统计 / 脏数据清理 / 增量更新"""
from fastapi import APIRouter
from pydantic import BaseModel

from app.rag import vector_admin

router = APIRouter(prefix="/api/vector", tags=["vector-admin"])


class RebuildRequest(BaseModel):
    content: str | None = None


@router.get("/collections")
def collections():
    """列出全部向量集合及块数"""
    return {"collections": vector_admin.list_collections()}


@router.get("/stats")
def stats(collection: str = "documents"):
    """集合统计：总量 / 按文档 / 按来源 / 孤儿块"""
    return vector_admin.collection_stats(collection)


@router.delete("/documents/{collection}/{doc}")
def delete_document(collection: str, doc: str):
    """删除指定文档的全部向量块（脏数据清理）"""
    return vector_admin.delete_document(collection, doc)


@router.post("/documents/{doc}/rebuild")
def rebuild_document(doc: str, req: RebuildRequest | None = None):
    """增量重建：先删旧块 → 重新向量化入库（文档修订后局部重建）"""
    content = req.content if req else None
    return vector_admin.rebuild_document(doc, content)


@router.post("/purge")
def purge(collection: str = "documents"):
    """清理孤儿块（源文件已删除的残留向量）"""
    return vector_admin.purge_orphans(collection)
