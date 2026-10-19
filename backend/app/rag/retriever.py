"""检索器：按游戏路由 + TopK 召回 + 相似度过滤（多路召回：名称命中 + 向量 + BM25 + 关键词兜底）"""
import json
import math
import re

from app.core.config import settings
from app.core.logging import get_logger
from app.knowledge.games import Game
from app.rag.embedding import get_embedding
from app.rag.vectorstore import get_vectorstore

logger = get_logger(__name__)


# 类型词 → 条目 type（query 命中类型词时对同类条目加权）
TYPE_WORDS = {
    "角色": "character", "圣遗物": "artifact", "配队": "team",
    "料理": "food", "武器": "weapon", "材料": "material",
}
# 元素/体系词：query 含元素词时，命中该词的条目小幅加权
ELEMENT_WORDS = ["火", "水", "雷", "冰", "风", "岩", "草", "蒸发", "融化", "激化", "超绽放", "永冻", "感电", "超载"]
# 体系词 → 涉及元素集合（用于元素×职能精确补充的展开匹配）
ELEMENT_GROUPS = {
    "火": ("火",), "水": ("水",), "雷": ("雷",), "冰": ("冰",), "风": ("风",),
    "岩": ("岩",), "草": ("草",),
    "蒸发": ("火", "水"), "融化": ("火", "冰"), "超载": ("火", "雷"),
    "超绽放": ("草", "雷"), "激化": ("雷", "草"), "永冻": ("冰", "水"), "感电": ("雷", "水"),
}
# 经典配队/体系简称：query 命中时直接补充对应 team 条目（覆盖词典盲区）
TEAM_SPECIALS = ["雷九万班", "万达国际", "胡行钟", "胡钟行", "雷国", "国家队列", "草行久", "那芙万"]


def _rerank(query: str, results: list[dict]) -> list[dict]:
    """轻量重排：类型词加权 + 元素词加权，再按分数排序"""
    q_types = [t for w, t in TYPE_WORDS.items() if w in query]
    q_els = [w for w in ELEMENT_WORDS if w in query]
    for r in results:
        meta = r.get("metadata") or {}
        score = 1.0 - r["distance"]
        if q_types and meta.get("type") in q_types:
            score += 0.15
        if q_els:
            text = r.get("text") or ""
            if any(w in text for w in q_els):
                score += 0.05
        r["_score"] = min(score, 1.0)
    results.sort(key=lambda r: -r["_score"])
    return results


class Retriever:
    """RAG 检索入口。

    TODO(阶段一)：
      - 相似度阈值过滤调优（score 与 distance 的换算）
      - 可选 bge-reranker 重排（加分项）
      - 元数据过滤（按条目类型）
    """

    def __init__(self):
        self._embedding = get_embedding()
        self._store = get_vectorstore()

    def retrieve(self, game: Game, query: str, top_k: int | None = None) -> list[dict]:
        """在指定游戏的知识集合中检索，返回带引用信息的条目（含相似度过滤）"""
        k = top_k or settings.retrieval_top_k
        q_vec = self._embedding.encode([query])[0]
        results = self._store.query(game.collection, q_vec, top_k=max(k * 2, 10))
        results = _rerank(query, results)
        out = []
        for r in results[:k]:
            score = r["_score"]
            if score < settings.retrieval_score_threshold:
                continue
            out.append(
                {
                    "doc_id": r["id"],
                    "title": (r["metadata"] or {}).get("title", r["id"]),
                    "content": r["text"],
                    "score": round(score, 4),
                    "source": (r["metadata"] or {}).get("source", "static"),
                }
            )
        logger.info("[%s] 向量检索 query=%r 命中 %d 条", game.game_id, query[:30], len(out))
        return out


retriever = Retriever()


# ---------- BM25 稀疏检索（P0-2：与向量构成多路召回；无外部依赖，按数据文件指纹缓存） ----------
def _tokenize(text: str) -> list[str]:
    """轻量中文分词：连续英文/数字整体成词 + 中文二元组（bigram），兼容中英混合查询"""
    tokens = [t.lower() for t in re.findall(r"[a-z0-9]+", text, flags=re.I)]
    han = re.sub(r"[^\u4e00-\u9fa5]", "", text)
    tokens.extend(han[i : i + 2] for i in range(max(len(han) - 1, 0)))
    return tokens


def _bm25_text(e: dict) -> str:
    """BM25 索引文本：名称 + 标题 + 摘要 + 角色/元素/武器 + 标签"""
    parts = [e.get("name", ""), e.get("title", ""), e.get("summary", ""),
             e.get("role", ""), e.get("element", ""), e.get("weapon_type", ""),
             " ".join(e.get("tags", []))]
    return " ".join(str(p) for p in parts if p)


class BM25Index:
    """Okapi BM25（k1=1.5, b=0.75）：面向小规模知识库的轻量实现"""

    def __init__(self, entries: list[dict]):
        self.docs = entries
        self.k1, self.b = 1.5, 0.75
        self.tf: list[dict[str, int]] = []
        self.df: dict[str, int] = {}
        self.doc_lens: list[int] = []
        for e in entries:
            toks = _tokenize(_bm25_text(e))
            self.doc_lens.append(len(toks))
            f: dict[str, int] = {}
            for t in toks:
                f[t] = f.get(t, 0) + 1
            self.tf.append(f)
            for t in set(toks):
                self.df[t] = self.df.get(t, 0) + 1
        self.avgdl = sum(self.doc_lens) / max(len(self.doc_lens), 1)

    def search(self, query: str, top_k: int = 8) -> list[tuple[int, float]]:
        qset = list(dict.fromkeys(_tokenize(query)))
        if not qset:
            return []
        n = max(len(self.docs), 1)
        scored: list[tuple[int, float]] = []
        for i in range(len(self.docs)):
            s = 0.0
            dl = self.doc_lens[i]
            for t in qset:
                f = self.tf[i].get(t, 0)
                if not f:
                    continue
                df = self.df.get(t, 0)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                tf_part = f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
                s += idf * tf_part
            if s > 0:
                scored.append((i, s))
        scored.sort(key=lambda t: -t[1])
        return scored[:top_k]


_bm25_cache: dict[str, tuple[float, BM25Index]] = {}
_entries_cache: dict[str, tuple[float, list[dict]]] = {}


def _data_mtime(data_dir) -> float:
    """数据目录指纹：包含 dynamic/ 子目录（arknights 的动态角色库 6.9MB 就在这里）。

    原实现只 stat 顶层 *.json，导致动态库更新后 BM25 索引与条目缓存永不失效。
    """
    mtimes = [p.stat().st_mtime for p in data_dir.rglob("*.json")]
    return max(mtimes, default=0.0)


def _get_bm25(game: Game) -> BM25Index:
    """按（数据目录, 文件最新 mtime）缓存 BM25 索引，避免每次请求重建"""
    mtime = _data_mtime(game.data_dir)
    key = str(game.data_dir)
    cached = _bm25_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    idx = BM25Index(_load_all_entries(game))
    _bm25_cache[key] = (mtime, idx)
    return idx


def _bm25_retrieve(game: Game, query: str, top_k: int = 5) -> list[dict]:
    """BM25 稀疏召回：原始分归一化到 [0, 1]（best 命中 = 1.0）

    注意：归一化后的 BM25 分与向量的余弦相似度**不可直接比较**，
    融合顺序由 hybrid_retrieve 的 RRF 排名决定，此处 score 仅用于展示。
    """
    idx = _get_bm25(game)
    hits = idx.search(query, top_k=top_k * 2)
    if not hits:
        return []
    best = hits[0][1]
    out: list[dict] = []
    for i, raw in hits[:top_k]:
        e = idx.docs[i]
        norm = raw / best if best > 0 else 0.0
        out.append({
            "doc_id": e.get("id", ""),
            "title": e.get("name", ""),
            "content": json.dumps({k: v for k, v in e.items() if k != "_meta"}, ensure_ascii=False),
            "source": e.get("source", "static"),
            "score": round(min(norm, 1.0), 4),
        })
    return out


def _rrf_fuse(doc_lists: list[list[dict]], k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion：按**排名**融合多路召回，避免不同分数尺度互相压制。

    原实现把 BM25 分缩放到 [0.55, 0.95] 后与余弦相似度（典型 0.35~0.7）取 max，
    结果是"BM25 必赢"——一个只命中单个二元组的垃圾词法命中会挤掉真正相关的语义命中。
    RRF 只用名次，天然免疫尺度问题。
    """
    fused: dict[str, dict] = {}
    rank_score: dict[str, float] = {}
    for docs in doc_lists:
        for rank, d in enumerate(docs, start=1):
            did = d["doc_id"]
            if did not in fused:
                fused[did] = dict(d)
                rank_score[did] = 0.0
            rank_score[did] += 1.0 / (k + rank)
            # 展示用分数取两路中的较高者，但排序只看 rank_score
            fused[did]["score"] = max(fused[did].get("score", 0.0), d.get("score", 0.0))
    ordered = sorted(fused.values(), key=lambda d: -rank_score[d["doc_id"]])
    return ordered


# ---------- 混合检索（名称命中置顶 + 向量召回 + BM25 + 关键词兜底，graph 与 ReAct 共用） ----------
KEYWORDS = [
    "火", "水", "雷", "冰", "风", "岩", "草", "蒸发", "融化", "永冻", "超绽放", "激化",
    "国家队", "直伤", "主C", "副C", "辅助", "治疗", "护盾", "平民", "配队",
]


def _load_all_entries(game: Game) -> list[dict]:
    """加载游戏全部知识条目（静态角色/武器/圣遗物/料理/材料 + 动态 + 配队）

    按数据目录指纹缓存：hybrid_retrieve 每轮对话会被调用 2-3 次，
    原实现每次都重新 json.loads 整个知识库（arknights 动态库 6.9MB）。
    """
    mtime = _data_mtime(game.data_dir)
    key = str(game.data_dir)
    cached = _entries_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]

    # 统一走 game_entity 的合并规则（动态覆盖静态 + 按名称去重），
    # 避免"检索层看到的条目"和"工具层查到的条目"不是同一份数据
    from app.tools.game_entity import load_all_entries as _load_game_entries

    out = _load_game_entries(game)
    _entries_cache[key] = (mtime, out)
    return out


def load_all_entries(game: Game) -> list[dict]:
    """公开入口（带 mtime 缓存）：供 graph 等调用方复用同一份合并/缓存结果"""
    return _load_all_entries(game)


def _name_match_score(query: str, name: str) -> tuple[int, int]:
    """名称匹配质量打分（2.2 修复：query 含多实体名时区分主次）。
    返回 (级别, 名称长度)；级别：精确等于 > query 以名称开头 > 名称在 query 中 > query 为名称子串。
    """
    if name == query:
        return 4, len(name)
    if name and query.startswith(name):
        return 3, len(name)
    if name and name in query:
        return 2, len(name)
    if name and query in name:
        return 1, len(name)
    return 0, 0


def hybrid_retrieve(game: Game, query: str, top_k: int = 4) -> list[dict]:
    """混合检索：① 名称命中（强信号置顶）→ ② 向量召回补充 → ③ 均未命中时关键词/全文兜底

    返回 docs：doc_id / title / content / source / score
    """
    entries = _load_all_entries(game)

    # ① 名称命中（置顶）：按匹配质量排序（精确 > 前缀 > 包含 > 子串），同分按名称长度降序
    name_hits: list[tuple[tuple[int, int], dict]] = []
    for e in entries:
        name = e.get("name", "")
        score_t = _name_match_score(query, name)
        if score_t[0] > 0:
            name_hits.append((score_t, e))
            continue
        if e.get("type") == "team" and query in (e.get("name", "") + e.get("summary", "")):
            name_hits.append(((2, len(name)), e))
    name_hits.sort(key=lambda t: (-t[0][0], -t[0][1]))
    name_docs = [
        {
            "doc_id": e.get("id", ""),
            "title": e.get("name", ""),
            "content": json.dumps({k: v for k, v in e.items() if k != "_meta"}, ensure_ascii=False),
            "source": e.get("source", "static"),
            "score": 1.0,
        }
        for _, e in name_hits[:3]
    ]

    # ② 多路召回：向量（语义）+ BM25（词法），用 RRF 按名次融合
    #    （原实现按 max(score) 合并，两个分数尺度不可比 → BM25 必然压制向量命中）
    vec_docs: list[dict] = []
    try:
        vec_docs = retriever.retrieve(game, query, top_k=5)
    except Exception as e:  # noqa: BLE001
        logger.warning("向量检索不可用，仅名称/BM25/关键词: %s", e)

    bm25_docs: list[dict] = []
    try:
        bm25_docs = _bm25_retrieve(game, query, top_k=5)
    except Exception as e:  # noqa: BLE001
        logger.warning("BM25 检索不可用，跳过稀疏路: %s", e)

    seen = {d["doc_id"] for d in name_docs}
    fused = [d for d in _rrf_fuse([vec_docs, bm25_docs]) if d["doc_id"] not in seen]
    docs = list(name_docs) + fused
    docs = docs[:top_k]

    # ③ 元素 × 职能精确补充（如"雷系副C"→ element=雷 且 role 含副C 的角色）
    # 2.3 修复：体系词（永冻/蒸发/激化等）展开为元素对；经典配队简称直接补充 team 条目
    FUNC_WORDS = ("主C", "副C", "辅助", "治疗", "护盾")
    q_els = [w for w in ELEMENT_GROUPS if w in query]
    expanded_els: set[str] = set()
    for w in q_els:
        expanded_els.update(ELEMENT_GROUPS[w])
    q_func = [w for w in FUNC_WORDS if w in query]
    if expanded_els and q_func:
        extra: list[dict] = []
        for e in entries:
            if e.get("type") != "character" or e.get("id") in seen:
                continue
            role = str(e.get("role", ""))
            if e.get("element") in expanded_els and any(f in role for f in q_func):
                extra.append(e)
        for e in extra[:2]:
            docs.append({
                "doc_id": e.get("id", ""),
                "title": e.get("name", ""),
                "content": json.dumps({k: v for k, v in e.items() if k != "_meta"}, ensure_ascii=False),
                "source": e.get("source", "static"),
                "score": 0.95,
            })
            seen.add(e.get("id", ""))
    # 2.3b：仅体系词（无职能词）或经典配队简称 → 补充匹配 team 条目与对应元素角色
    elif expanded_els or any(s in query for s in TEAM_SPECIALS):
        extra2: list[dict] = []
        team_hit = next(
            (e for e in entries
             if e.get("type") == "team" and e.get("id") not in seen
             and any(s in (e.get("name", "") + e.get("summary", "")) for s in (*TEAM_SPECIALS, *q_els))),
            None,
        )
        if team_hit:
            extra2.append(team_hit)
            seen.add(team_hit.get("id", ""))
        for e in entries:
            if e.get("type") != "character" or e.get("id") in seen or len(extra2) >= 2:
                continue
            if expanded_els and e.get("element") in expanded_els:
                extra2.append(e)
                seen.add(e.get("id", ""))
        for e in extra2:
            docs.append({
                "doc_id": e.get("id", ""),
                "title": e.get("name", ""),
                "content": json.dumps({k: v for k, v in e.items() if k != "_meta"}, ensure_ascii=False),
                "source": e.get("source", "static"),
                "score": 0.95,
            })

    # ④ 关键词 / 全文兜底（docs 为空时）
    if not docs:
        hits: list[dict] = []
        q_words = [k for k in KEYWORDS if k in query]
        if q_words:
            team_hits, other_hits = [], []
            for e in entries:
                text = e.get("name", "") + e.get("summary", "") + " ".join(e.get("tags", [])) + e.get("core", "")
                if any(w in text for w in q_words):
                    (team_hits if e.get("type") == "team" else other_hits).append(e)
            hits = (team_hits + other_hits)[:3]
        if not hits:
            for e in entries:
                text = json.dumps(e, ensure_ascii=False).lower()
                if query.lower() in text:
                    hits.append(e)
        hits = hits[:3]
        docs = [
            {
                "doc_id": e.get("id", ""),
                "title": e.get("name", ""),
                "content": json.dumps({k: v for k, v in e.items() if k != "_meta"}, ensure_ascii=False),
                "source": e.get("source", "static"),
            }
            for e in hits
        ]
    return docs
