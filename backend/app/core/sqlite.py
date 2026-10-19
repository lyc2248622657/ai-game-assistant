"""SQLite 连接管理：统一的连接生命周期与并发设置。

为什么需要这个模块：
  `with sqlite3.connect(...) as conn:` 只管理**事务**（成功 commit / 失败 rollback），
  并**不会关闭连接**。正常路径靠引用计数回收，但异常路径上 traceback 会持有栈帧，
  连接（及其文件句柄）会与异常对象同寿命——而 FastAPI 会把异常链保留在 500 响应里，
  于是长时间运行 + 频繁报错会持续积累句柄。

本模块的 `connect()` 上下文管理器在退出时无条件 `close()`，并统一设置：
  - `journal_mode=WAL`：读写不互斥，避免线程池并发写的 "database is locked"；
  - `synchronous=NORMAL`：WAL 下的安全/性能平衡点；
  - `busy_timeout`：拿不到锁时等待而不是立刻报错。
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

BUSY_TIMEOUT_MS = 5000


@contextmanager
def connect(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    """打开连接 → yield → commit/rollback → 必定 close。"""
    conn = sqlite3.connect(str(db_path), timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    try:
        # PRAGMA 必须在任何隐式事务开始前执行
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
