"""会话记忆：SQLite 持久化存储（基础框架版）"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.sqlite import connect


class SessionStore:
    """基于 SQLite 的会话存储。

    TODO(阶段二)：
      - 消息按窗口裁剪 + 超窗摘要压缩（记忆注入）
      - 会话列表分页
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = Path(db_path or settings.sqlite_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @staticmethod
    def _row_to_session(row) -> dict:
        """行 → 会话字典（message_count 由 SQL 聚合列提供）"""
        return {
            "session_id": row["session_id"],
            "game_id": row["game_id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "message_count": int(row["message_count"] or 0),
        }

    _COUNT_SQL = (
        "SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.session_id)"
        " AS message_count FROM sessions s"
    )

    def _init_db(self) -> None:
        with connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    game_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '新会话',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    citations TEXT,          -- JSON 数组
                    images TEXT,             -- 相关图片 URL 列表（JSON 数组，回答配图 A/B）
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id, id);
                """
            )
        # 兼容旧库：早版本 messages 无 images 列 → 增量补列
        with connect(self.db_path) as conn:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
            if "images" not in cols:
                conn.execute("ALTER TABLE messages ADD COLUMN images TEXT")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # --- 会话 ---
    def create_session(self, game_id: str, title: str = "新会话") -> dict:
        session_id = uuid.uuid4().hex[:16]
        now = self._now()
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO sessions(session_id, game_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
                (session_id, game_id, title, now, now),
            )
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> dict:
        with connect(self.db_path) as conn:
            row = conn.execute(
                f"{self._COUNT_SQL} WHERE s.session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise AppError(ErrorCode.SESSION_NOT_FOUND, f"会话不存在: {session_id}")
        return self._row_to_session(row)

    def update_session_title(self, session_id: str, title: str) -> None:
        """更新会话标题（智能命名）"""
        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE sessions SET title = ? WHERE session_id = ?", (title, session_id)
            )

    def list_sessions(self, game_id: str | None = None) -> list[dict]:
        """会话列表：message_count 由 SQL 聚合一次算出（原实现是每行再查一次，N+1）"""
        sql, params = self._COUNT_SQL, ()
        if game_id:
            sql += " WHERE s.game_id = ?"
            params = (game_id,)
        sql += " ORDER BY s.updated_at DESC"
        with connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_session(r) for r in rows]

    # --- 消息 ---
    def add_message(
        self, session_id: str, role: str, content: str, citations: list | None = None,
        images: list | None = None,
    ) -> None:
        now = self._now()
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages(session_id, role, content, citations, images, created_at) VALUES (?,?,?,?,?,?)",
                (session_id, role, content, json.dumps(citations or [], ensure_ascii=False),
                 json.dumps(images or [], ensure_ascii=False), now),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id)
            )

    def get_messages(self, session_id: str, limit: int | None = None) -> list[dict]:
        with connect(self.db_path) as conn:
            if limit:
                rows = conn.execute(
                    "SELECT * FROM (SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,)
                ).fetchall()
        return [
            {
                "id": r["id"],  # 消息自增 id（增量摘要压缩用）
                "role": r["role"],
                "content": r["content"],
                "citations": json.loads(r["citations"] or "[]"),
                "images": json.loads(r["images"] or "[]"),
            }
            for r in rows
        ]

    def count_messages(self, session_id: str) -> int:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE session_id = ?", (session_id,)
            ).fetchone()
        return int(row["c"])

    def delete_session(self, session_id: str) -> None:
        """删除会话及其全部消息（前端"删除对话"按钮调用）"""
        with connect(self.db_path) as conn:
            # 先确认存在（不存在抛 404 语义）
            row = conn.execute(
                "SELECT session_id FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise AppError(ErrorCode.SESSION_NOT_FOUND, f"会话不存在: {session_id}")
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


store = SessionStore()
