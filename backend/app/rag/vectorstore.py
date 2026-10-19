"""向量库封装：Chroma，按游戏隔离 Collection"""
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class VectorStore:
    """Chroma 本地持久化封装。

    关键设计：每个游戏一个独立 collection（按游戏隔离），
    检索时按 game_id 路由，多游戏数据互不干扰。
    """

    def __init__(self, persist_dir: str | None = None):
        self._persist_dir = Path(persist_dir or settings.chroma_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            import chromadb

            self._client = chromadb.PersistentClient(path=str(self._persist_dir))
            logger.info("Chroma 已连接: %s", self._persist_dir)
        return self._client

    def get_collection(self, collection: str):
        """获取（不存在则创建）指定游戏的知识集合"""
        client = self._ensure_client()
        return client.get_or_create_collection(
            name=collection, metadata={"hnsw:space": "cosine"}
        )

    def upsert(self, collection: str, ids: list[str], texts: list[str], metadatas: list[dict], embeddings: list[list[float]]) -> None:
        col = self.get_collection(collection)
        col.upsert(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)

    def query(
        self,
        collection: str,
        query_embedding: list[float],
        top_k: int = 5,
        where: dict | None = None,
    ) -> list[dict]:
        """按向量检索，返回 [{id, text, metadata, distance}]

        where: Chroma 元数据过滤（如 {"game_id": "genshin"}）。原实现没有这个参数，
        调用方只能"先取 2*k 再在 Python 里过滤"，跨游戏记忆会互相挤占召回名额。
        """
        col = self.get_collection(collection)
        kwargs = dict(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        if where:
            kwargs["where"] = where
        res = col.query(**kwargs)
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        ids = res.get("ids", [[]])[0]
        out = []
        for i in range(len(docs)):
            out.append(
                {
                    "id": ids[i],
                    "text": docs[i],
                    "metadata": metas[i] or {},
                    "distance": dists[i],
                }
            )
        return out

    def count(self, collection: str) -> int:
        return self.get_collection(collection).count()

    def list_collections(self) -> list[dict]:
        """列出所有集合及块数（运维/诊断用）"""
        client = self._ensure_client()
        out = []
        for c in client.list_collections():
            out.append({"name": c.name, "count": c.count()})
        return sorted(out, key=lambda x: x["name"])

    def get_all(self, collection: str) -> dict:
        """全量拉取 ids + metadatas（供统计与孤儿块检测）"""
        col = self.get_collection(collection)
        res = col.get(include=["metadatas"])
        return {
            "ids": res.get("ids", []) or [],
            "metadatas": res.get("metadatas", []) or [],
        }

    def delete_by_metadata(self, collection: str, where: dict) -> int:
        """按元数据过滤删除（脏数据清理），返回删除条数"""
        col = self.get_collection(collection)
        got = col.get(where=where, include=[])
        ids = got.get("ids", []) or []
        if ids:
            col.delete(ids=ids)
        return len(ids)

    def delete_collection(self, collection: str) -> None:
        """整集合删除（用于全量重建，谨慎调用）"""
        self._ensure_client().delete_collection(collection)


@lru_cache
def get_vectorstore() -> VectorStore:
    return VectorStore()
