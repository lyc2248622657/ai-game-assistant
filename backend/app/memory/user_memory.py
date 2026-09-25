"""用户级长期记忆：偏好提取与存储（按游戏隔离，阶段三 P1）

机制：对话中 LLM 提取玩家偏好线索（常问实体/关注点/玩法倾向），
写入 SQLite user_prefs 表（game_id 隔离）；新对话注入 system prompt 持续生效。
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.agents.llm import get_chat_model
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_PREFS = 12  # 每个游戏最多保留偏好条数


class UserMemory:
    """用户偏好：提取 / 读取 / 更新（按 game_id 隔离）"""

    def __init__(self, db_path: str | None = None):
        self.db_path = Path(db_path or settings.sqlite_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_prefs (
                    game_id TEXT NOT NULL,
                    pref TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (game_id, pref)
                );
                """
            )

    # --- 读取 ---
    def get_prefs(self, game_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT pref FROM user_prefs WHERE game_id = ? ORDER BY updated_at DESC",
                (game_id,),
            ).fetchall()
        return [r["pref"] for r in rows]

    # --- 提取并存储 ---
    def extract_and_store(self, game_id: str, messages: list[dict]) -> int:
        """从最近对话提取玩家偏好并入库；返回新增/更新的条数"""
        recent = [m for m in messages if m.get("role") in ("user", "assistant")][-8:]
        if not recent:
            return 0
        try:
            model = get_chat_model()
            transcript = "\n".join(
                f"{'用户' if m['role'] == 'user' else '助手'}: {m['content'][:200]}" for m in recent
            )
            resp = model.invoke(
                [
                    {
                        "role": "system",
                        "content": (
                            "从对话中提取该玩家的稳定偏好线索（如常问的角色/体系、玩法倾向、关注点），"
                            "每条不超过 20 字，只保留有依据的线索，没有则输出空数组。"
                            '只输出 JSON：{"prefs": ["线索1", "线索2"]}'
                        ),
                    },
                    {"role": "user", "content": transcript},
                ]
            )
            m = re.search(r"\{.*\}", resp.content or "", re.S)
            prefs = json.loads(m.group(0)).get("prefs", []) if m else []
            prefs = [str(p).strip()[:20] for p in prefs if str(p).strip()]
            if not prefs:
                return 0
            now = datetime.now(timezone.utc).isoformat()
            with self._connect() as conn:
                for p in prefs:
                    conn.execute(
                        "INSERT INTO user_prefs(game_id, pref, updated_at) VALUES (?,?,?) "
                        "ON CONFLICT(game_id, pref) DO UPDATE SET updated_at = excluded.updated_at",
                        (game_id, p, now),
                    )
                # 控制条数：超限删除最旧的
                conn.execute(
                    "DELETE FROM user_prefs WHERE game_id = ? AND pref NOT IN "
                    "(SELECT pref FROM user_prefs WHERE game_id = ? ORDER BY updated_at DESC LIMIT ?)",
                    (game_id, game_id, MAX_PREFS),
                )
            logger.info("[mem] 用户偏好已更新: %s +%d 条", game_id, len(prefs))
            return len(prefs)
        except Exception as e:  # noqa: BLE001
            logger.warning("[mem] 偏好提取失败: %s", e)
            return 0


user_memory = UserMemory()
