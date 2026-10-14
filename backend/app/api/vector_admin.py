"""向量库运维 API：统计 / 脏数据清理 / 增量更新"""
from fastapi import APIRouter
from pydantic import BaseModel

from app.rag import vector_admin

router = APIRouter(prefix="/api/vector", tags=["vector-admin"])


class RebuildRequest(BaseModel):
    content: str | None = None


class SearchRequest(BaseModel):
    game_id: str = "genshin"
    query: str
    top_k: int = 4


@router.post("/search")
def search(req: SearchRequest):
    """检索测试：对指定游戏知识库执行混合检索，返回带相似度的结果（管理控制台用）"""
    from app.knowledge.games import registry
    from app.rag.retriever import hybrid_retrieve

    game = registry.get_game(req.game_id)
    docs = hybrid_retrieve(game, req.query.strip(), top_k=max(1, min(req.top_k, 10)))
    return {"game_id": req.game_id, "query": req.query, "docs": docs}


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
