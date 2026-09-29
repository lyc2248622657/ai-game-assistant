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
            if "summary_from" not in cols:
                conn.execute("ALTER TABLE sessions ADD COLUMN summary_from INTEGER DEFAULT 0")
                conn.commit()
                logger.info("sessions 表新增 summary_from 列（增量压缩游标）")

    # --- 读取 ---
    def get_summary(self, session_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT summary FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return (row["summary"] or None) if row else None

    def _get_summary_from(self, session_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT summary_from FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return int((row["summary_from"] or 0)) if row else 0

    # --- 生成/更新摘要（增量压缩：只压缩游标之后的新消息，transcript 有界） ---
    def refresh(self, session_id: str, game_id: str) -> str | None:
        """消息达到阈值时压缩为摘要；失败返回 None（不阻塞主流程）。

        4.2 修复：以 summary_from 游标做增量压缩——旧摘要 + 游标后的新消息重新压缩，
        避免 transcript 随轮次线性增长（token 成本有界），同时早期轮次信息通过旧摘要保留。
        """
        msgs = self.store.get_messages(session_id)
        if len(msgs) < SUMMARY_THRESHOLD:
            return None
        cursor = self._get_summary_from(session_id)
        # 游标之后、最近 2 条之前（压缩已完成轮次，保留进行中上下文）
        pending = [m for m in msgs if m["id"] > cursor][:-2]
        if not pending:
            return self.get_summary(session_id)
        try:
            model = get_chat_model()
            old_summary = self.get_summary(session_id)
            transcript_parts = []
            if old_summary:
                transcript_parts.append(f"[此前对话摘要]\n{old_summary}")
            transcript_parts.append(
                "\n".join(
                    f"{'用户' if m['role'] == 'user' else '助手'}: {m['content'][:300]}"
                    for m in pending
                )
            )
            resp = model.invoke(
                [
                    {
                        "role": "system",
                        "content": "把以下内容压缩成 3~5 行中文摘要（含此前摘要时需融合保留其关键信息），保留：玩家问过的主题/实体、助手给出的关键结论、玩家偏好线索。只输出摘要正文。",
                    },
                    {"role": "user", "content": "\n".join(transcript_parts)},
                ]
            )
            summary = (resp.content or "").strip()
            if not summary:
                return None
            last_id = pending[-1]["id"]
            with self._connect() as conn:
                conn.execute(
                    "UPDATE sessions SET summary = ?, summary_from = ?, updated_at = ? WHERE session_id = ?",
                    (summary, last_id, datetime.now(timezone.utc).isoformat(), session_id),
                )
            logger.info("[mem] 会话摘要已增量更新: %s（游标 → %s）", session_id, last_id)
            return summary
        except Exception as e:  # noqa: BLE001
            logger.warning("[mem] 摘要生成失败: %s", e)
            return None


session_memory = SessionMemory()
