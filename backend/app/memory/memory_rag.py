"""记忆型 Agent：记忆向量化检索（Memory RAG，阶段三 P2）

MemGPT 式分层记忆的落地子集：
  - 核心记忆（core）：用户偏好（全量注入，见 user_memory.py）
  - 工作记忆（working）：当前会话摘要（见 session_memory.py）
  - 外部记忆（external）：历史会话的关键事实（会话摘要 / 偏好 / 常问实体），
    向量化存入 Chroma「user_memory」collection，问答前按相关性召回注入。

设计要点：
  - 复用本地 bge-small-zh embedding + Chroma，不依赖外部服务；
  - 每条记忆带 metadata {game_id, kind, ts}，按游戏隔离、按类型可追溯；
  - 写入由 chat 流程在对话结束后异步触发（失败不阻塞主流程）；
  - 检索为空/向量库不可用时静默降级（返回空列表）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.core.logging import get_logger
from app.rag.embedding import get_embedding
from app.rag.vectorstore import get_vectorstore

logger = get_logger(__name__)

COLLECTION = "user_memory"
MEMORY_TOP_K = 5


class MemoryRAG:
    """记忆向量库：写入（摘要/偏好/常问实体）+ 检索（按相关性召回）"""

    def __init__(self):
        self._embedding = get_embedding()
        self._store = get_vectorstore()

    # ---------- 写入 ----------
    def upsert_session(
        self,
        game_id: str,
        session_id: str,
        summary: Optional[str] = None,
        prefs: Optional[list[str]] = None,
        entities: Optional[list[str]] = None,
    ) -> int:
        """把一次会话产生的记忆事实向量化入库；返回写入条数"""
        texts: list[str] = []
        metas: list[dict] = []
        ids: list[str] = []
        now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        def _add(kind: str, text: str, key: str) -> None:
            text = str(text).strip()
            if not text:
                return
            texts.append(text)
            metas.append({"game_id": game_id, "kind": kind, "ts": now, "session_id": session_id})
            ids.append(f"{game_id}:{kind}:{key}")

        if summary:
            _add("summary", f"会话摘要：{summary}", f"sum:{session_id}")
        for i, p in enumerate(prefs or []):
            _add("pref", f"玩家偏好：{p}", f"pref:{i}")
        for i, e in enumerate(entities or []):
            _add("entity", f"用户近期关注实体：{e}", f"ent:{i}")

        if not texts:
            return 0
        try:
            vectors = self._embedding.encode(texts)
            self._store.upsert(COLLECTION, ids, texts, metas, vectors)
            logger.info("[mem-rag] 记忆入库 %s: +%d 条", game_id, len(texts))
            return len(texts)
        except Exception as e:  # noqa: BLE001
            logger.warning("[mem-rag] 记忆写入失败（降级）: %s", e)
            return 0

    # ---------- 检索 ----------
    def retrieve(self, game_id: str, query: str, top_k: int = MEMORY_TOP_K) -> list[dict]:
        """按语义召回与当前问题相关的历史记忆；不可用/无命中返回空列表"""
        if not query.strip():
            return []
        try:
            q_vec = self._embedding.encode([query])[0]
            res = self._store.query(COLLECTION, q_vec, top_k=max(top_k * 2, 10))
        except Exception as e:  # noqa: BLE001
            logger.warning("[mem-rag] 记忆检索不可用（降级）: %s", e)
            return []
        out: list[dict] = []
        for r in res:
            meta = r.get("metadata") or {}
            if meta.get("game_id") not in (game_id, "", None):
                continue  # 按游戏隔离，不串游戏
            score = 1.0 - r["distance"]
            if score < 0.35:
                continue
            out.append(
                {
                    "kind": meta.get("kind", "unknown"),
                    "text": r.get("text", ""),
                    "score": round(score, 4),
                    "ts": meta.get("ts", ""),
                }
            )
        return out[:top_k]


memory_rag = MemoryRAG()
