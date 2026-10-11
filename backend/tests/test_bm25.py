"""BM25 稀疏检索单测：分词 / 索引命中 / 混合检索融合（不加载向量模型，纯逻辑）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag.retriever import BM25Index, _tokenize  # noqa: E402


def test_tokenize_mixed():
    """中英混合分词：中文二元组 + 英文整体小写词"""
    toks = _tokenize("能天使Ash")
    assert "能天" in toks
    assert "天使" in toks
    assert "ash" in toks


def test_tokenize_pure_english():
    assert "bge" in _tokenize("BGE reranker 重排")


def test_bm25_hits_exact_name():
    """查询干员名 → 对应条目排第一"""
    entries = [
        {"id": "char_能天使", "name": "能天使", "title": "企鹅物流的信使",
         "summary": "狙击职业速射手分支，高攻速物理输出", "role": "狙击（速射手）",
         "element": "物理", "weapon_type": "远程", "tags": ["狙击", "速射手", "物理"]},
        {"id": "char_银灰", "name": "银灰", "title": "谢拉格的传奇",
         "summary": "近卫职业领主分支，真银斩清场", "role": "近卫（领主）",
         "element": "物理", "weapon_type": "近战", "tags": ["近卫", "领主", "物理"]},
    ]
    idx = BM25Index(entries)
    hits = idx.search("能天使", top_k=2)
    assert hits and entries[hits[0][0]]["id"] == "char_能天使"


def test_bm25_zh_compound_query():
    """中文复合查询命中语义相关条目（bigram 词项重合）"""
    entries = [
        {"id": "a", "name": "原神七种元素", "summary": "火水雷冰风岩草七种元素",
         "role": "", "element": "", "weapon_type": "", "tags": ["元素", "基础"]},
        {"id": "b", "name": "蒸发反应", "summary": "水与火接触触发增幅反应",
         "role": "", "element": "", "weapon_type": "", "tags": ["反应", "蒸发"]},
    ]
    idx = BM25Index(entries)
    hits = idx.search("火元素", top_k=2)
    assert hits[0][0] == 0  # "火元素" → 元素条目


def test_bm25_no_query_returns_empty():
    idx = BM25Index([{"id": "x", "name": "测试", "summary": "内容"}])
    assert idx.search("") == []
