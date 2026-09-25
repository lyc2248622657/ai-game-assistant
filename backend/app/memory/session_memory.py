"""会话级记忆：摘要滚动压缩（跨轮次延续上下文，阶段三 P1）

机制：会话消息达到阈值后，LLM 将早期对话压缩为摘要持久化；
新轮次通过 prompts.prepare_history 注入（摘要 + 最近 N 条）。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.agents.llm import get_chat_model
from app.core.config import settings
from app.core.logging import get_logger
from app.memory.store import SessionStore

logger = get_logger(__name__)

SUMMARY_THRESHOLD = 12  # 消息数达到该值即生成/更新摘要


class SessionMemory:
    """会话摘要：读取/生成/更新（基于现有 SQLite 存储）"""

    def __init__(self, store: SessionStore | None = None):
        self.store = store or SessionStore()
        self._ensure_summary_column()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_summary_column(self) -> None:
        with self._connect() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
            if "summary" not in cols:
                conn.execute("ALTER TABLE sessions ADD COLUMN summary TEXT")
                conn.commit()
                logger.info("sessions 表新增 summary 列")

    # --- 读取 ---
    def get_summary(self, session_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT summary FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return (row["summary"] or None) if row else None

    # --- 生成/更新摘要 ---
    def refresh(self, session_id: str, game_id: str) -> str | None:
        """消息达到阈值时压缩为摘要；失败返回 None（不阻塞主流程）"""
        msgs = self.store.get_messages(session_id)
        if len(msgs) < SUMMARY_THRESHOLD:
            return None
        try:
            model = get_chat_model()
            transcript = "\n".join(
                f"{'用户' if m['role'] == 'user' else '助手'}: {m['content'][:300]}"
                for m in msgs[:-2]
            )
            resp = model.invoke(
                [
                    {
                        "role": "system",
                        "content": "把以下对话压缩成 3~5 行中文摘要，保留：玩家问过的主题/实体、助手给出的关键结论、玩家偏好线索。只输出摘要正文。",
                    },
                    {"role": "user", "content": transcript},
                ]
            )
            summary = (resp.content or "").strip()
            if not summary:
                return None
            with self._connect() as conn:
                conn.execute(
                    "UPDATE sessions SET summary = ?, updated_at = ? WHERE session_id = ?",
                    (summary, datetime.now(timezone.utc).isoformat(), session_id),
                )
            logger.info("[mem] 会话摘要已更新: %s", session_id)
            return summary
        except Exception as e:  # noqa: BLE001
            logger.warning("[mem] 摘要生成失败: %s", e)
            return None


session_memory = SessionMemory()
