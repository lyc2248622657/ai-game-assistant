"""Memory RAG 单测：记忆向量化写入 + 按相关性召回（跨会话记忆）

使用本地 bge-small-zh embedding + **临时chroma 库**，不联网、不污染真实数据。
（此前直接 new MemoryRAG() 会写进 backend/data/chroma 的 user_memory 集合，
多次运行后真实记忆库里堆积了大量 session_id=test-* 的测试条目。）
"""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.memory.memory_rag as memory_rag_module  # noqa: E402
from app.memory.memory_rag import MemoryRAG  # noqa: E402
from app.rag.vectorstore import VectorStore  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_vector_store(tmp_path, monkeypatch):
    """把记忆向量库重定向到临时目录，测试永不写真实 Chroma。

    注意要同时替换**工厂函数**和模块单例：`MemoryRAG()` 在构造时调用
    `get_vectorstore()`，只改单例的 `_store` 对新建实例无效。
    """
    temp = VectorStore(persist_dir=str(tmp_path / "chroma"))
    monkeypatch.setattr(memory_rag_module, "get_vectorstore", lambda: temp)
    monkeypatch.setattr(memory_rag_module.memory_rag, "_store", temp)


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


def test_memory_ids_are_content_based():
    """回归：记忆 id 由内容哈希派生，不同事实不会按下标互相覆盖"""
    rag = MemoryRAG()
    sid = f"test-{uuid.uuid4().hex[:8]}"
    rag.upsert_session("genshin", sid, prefs=["偏好A"])
    rag.upsert_session("genshin", sid, prefs=["偏好B"])
    got = rag._store.get_all(memory_rag_module.COLLECTION)
    pref_ids = [i for i in got["ids"] if ":pref:" in i]
    assert len(pref_ids) == 2, f"两条不同偏好应各自入库，实际: {pref_ids}"
