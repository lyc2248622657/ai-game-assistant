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

    def query(self, collection: str, query_embedding: list[float], top_k: int = 5) -> list[dict]:
        """按向量检索，返回 [{id, text, metadata, distance}]"""
        col = self.get_collection(collection)
        res = col.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
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


@lru_cache
def get_vectorstore() -> VectorStore:
    return VectorStore()
