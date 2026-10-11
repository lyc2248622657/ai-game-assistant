"""向量库运维单测：统计聚合 / 按文档删除 / 孤儿清理 / 增量重建（mock，不碰真实库）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag import vector_admin  # noqa: E402


class _FakeCol:
    """伪 Chroma collection：直接操作底层共享列表（引用一致，删除可回读）"""

    def __init__(self, ids_ref, metas_ref):
        self._ids = ids_ref
        self._metas = metas_ref

    def get(self, where=None, include=None):
        keep = []
        for i, m in zip(self._ids, self._metas):
            if where is None or all(m.get(k) == v for k, v in where.items()):
                keep.append(i)
        return {"ids": keep}

    def delete(self, ids=None):
        id_set = set(ids or [])
        keep = [(i, m) for i, m in zip(self._ids, self._metas) if i not in id_set]
        self._ids[:] = [i for i, _ in keep]
        self._metas[:] = [m for _, m in keep]
        return None


class _FakeStore:
    def __init__(self, collections):
        self._cols = {name: {"ids": list(d["ids"]), "metas": [dict(m) for m in d["metas"]]} for name, d in collections.items()}
        self.deleted_by_meta = []

    def list_collections(self):
        return [{"name": n, "count": len(c["ids"])} for n, c in sorted(self._cols.items())]

    def get_all(self, collection):
        c = self._cols[collection]
        return {"ids": list(c["ids"]), "metadatas": [dict(m) for m in c["metas"]]}

    def delete_by_metadata(self, collection, where):
        c = self._cols[collection]
        keep = [(i, m) for i, m in zip(c["ids"], c["metas"]) if not all(m.get(k) == v for k, v in where.items())]
        deleted = len(c["ids"]) - len(keep)
        c["ids"], c["metas"] = [i for i, _ in keep], [m for _, m in keep]
        self.deleted_by_meta.append((collection, dict(where), deleted))
        return deleted

    def get_collection(self, collection):
        c = self._cols[collection]
        return _FakeCol(c["ids"], c["metas"])


def _sample_collections():
    return {
        "documents": {
            "ids": ["制度::0", "制度::1", "手册::0", "旧文档::0"],
            "metas": [
                {"source": "document_qa", "doc": "示例公司员工制度手册", "title": "示例公司员工制度手册"},
                {"source": "document_qa", "doc": "示例公司员工制度手册", "title": "示例公司员工制度手册"},
                {"source": "document_qa", "doc": "入职手册", "title": "入职手册"},
                {"source": "document_qa", "doc": "已删除文档", "title": "已删除文档"},
            ],
        },
        "genshin": {
            "ids": ["g1", "g2"],
            "metas": [{"source": "wiki", "game": "genshin"}, {"source": "wiki", "game": "genshin"}],
        },
    }


def test_list_collections(monkeypatch):
    store = _FakeStore(_sample_collections())
    monkeypatch.setattr(vector_admin, "get_vectorstore", lambda: store)
    assert vector_admin.list_collections() == [
        {"name": "documents", "count": 4},
        {"name": "genshin", "count": 2},
    ]


def test_collection_stats_aggregates_and_detects_orphans(monkeypatch, tmp_path):
    store = _FakeStore(_sample_collections())
    monkeypatch.setattr(vector_admin, "get_vectorstore", lambda: store)
    # 只有「示例公司员工制度手册」「入职手册」文件存在 → 「已删除文档」成为孤儿
    (tmp_path / "示例公司员工制度手册.md").write_text("x", encoding="utf-8")
    (tmp_path / "入职手册.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(vector_admin.document_qa, "DOC_DIR", tmp_path)

    s = vector_admin.collection_stats("documents")
    assert s["total"] == 4
    assert s["by_doc"]["示例公司员工制度手册"] == 2
    assert s["by_source"]["document_qa"] == 4
    assert s["orphan_docs"] == ["已删除文档"]
    assert s["orphan_chunk_count"] == 1


def test_delete_document_removes_only_target(monkeypatch):
    store = _FakeStore(_sample_collections())
    monkeypatch.setattr(vector_admin, "get_vectorstore", lambda: store)
    r = vector_admin.delete_document("documents", "示例公司员工制度手册")
    assert r["deleted_chunks"] == 2
    assert store._cols["documents"]["ids"] == ["手册::0", "旧文档::0"]


def test_purge_orphans(monkeypatch, tmp_path):
    store = _FakeStore(_sample_collections())
    monkeypatch.setattr(vector_admin, "get_vectorstore", lambda: store)
    (tmp_path / "示例公司员工制度手册.md").write_text("x", encoding="utf-8")
    (tmp_path / "入职手册.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(vector_admin.document_qa, "DOC_DIR", tmp_path)

    r = vector_admin.purge_orphans("documents")
    assert r["purged_chunks"] == 1  # 仅「已删除文档」
    assert "旧文档::0" not in store._cols["documents"]["ids"]


def test_rebuild_deletes_then_reingests(monkeypatch, tmp_path):
    store = _FakeStore(_sample_collections())
    monkeypatch.setattr(vector_admin, "get_vectorstore", lambda: store)
    (tmp_path / "示例公司员工制度手册.md").write_text("新版内容", encoding="utf-8")
    monkeypatch.setattr(vector_admin.document_qa, "DOC_DIR", tmp_path)
    monkeypatch.setattr(
        vector_admin.document_qa,
        "ingest_document",
        lambda name, content: {"name": name, "chunks": 1, "path": str(tmp_path / f"{name}.md")},
    )
    monkeypatch.setattr(
        vector_admin.document_qa, "get_embedding", lambda: type("E", (), {"encode": lambda self, t: [[0.1] * 4] * len(t)})()
    )

    r = vector_admin.rebuild_document("示例公司员工制度手册")
    assert r["ok"] is True
    assert r["deleted_chunks"] == 2   # 旧块先删
    assert r["chunks"] == 1           # 新块再入
    # 删除确实发生
    assert any(coll == "documents" and where.get("doc") == "示例公司员工制度手册" and n == 2 for coll, where, n in store.deleted_by_meta)


def test_rebuild_missing_doc_returns_error(monkeypatch, tmp_path):
    store = _FakeStore(_sample_collections())
    monkeypatch.setattr(vector_admin, "get_vectorstore", lambda: store)
    monkeypatch.setattr(vector_admin.document_qa, "DOC_DIR", tmp_path)  # 空目录，无文件
    r = vector_admin.rebuild_document("不存在的文档")
    assert r["ok"] is False
    assert "不存在" in r["message"]
