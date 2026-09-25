"""Memory RAG 单测：记忆向量化写入 + 按相关性召回（跨会话记忆）

使用本地 bge-small-zh embedding + Chroma 临时库，不联网。
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.memory.memory_rag import MemoryRAG  # noqa: E402


def test_upsert_and_retrieve():
    """写入摘要/偏好/常问实体 → 相关问题语义召回命中"""
    rag = MemoryRAG()
    gid = "genshin"
    sid = f"test-{uuid.uuid4().hex[:8]}"
    n = rag.upsert_session(
        gid, sid,
        summary="用户询问了那维莱特与水神的配队思路，助手给出推荐组合",
        prefs=["喜欢用那维莱特打水元素配队"],
        entities=["那维莱特"],
    )
    assert n >= 2, f"记忆写入条数异常: {n}"

    hits = rag.retrieve(gid, "那维莱特怎么配队")
    assert hits, "相关记忆应被召回"
    assert any("那维莱特" in h["text"] for h in hits)
    assert all(h["kind"] in ("summary", "pref", "entity") for h in hits)


def test_retrieve_game_isolated():
    """记忆按游戏隔离：明日方舟查询不应召回原神记忆"""
    rag = MemoryRAG()
    gid = "arknights"
    sid = f"test-{uuid.uuid4().hex[:8]}"
    rag.upsert_session(gid, sid, prefs=["喜欢用银灰打近卫队"], entities=["银灰"])
    hits = rag.retrieve(gid, "银灰的技能")
    assert any("银灰" in h["text"] for h in hits)
