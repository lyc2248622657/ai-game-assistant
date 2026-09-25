"""检索器：按游戏路由 + TopK 召回 + 相似度过滤"""
import json

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
ELEMENT_WORDS = ["火", "水", "雷", "冰", "风", "岩", "草", "蒸发", "融化", "激化", "超绽放"]


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


# ---------- 混合检索（名称命中置顶 + 向量召回 + 关键词兜底，graph 与 ReAct 共用） ----------
KEYWORDS = [
    "火", "水", "雷", "冰", "风", "岩", "草", "蒸发", "融化", "永冻", "超绽放", "激化",
    "国家队", "直伤", "主C", "副C", "辅助", "治疗", "护盾", "平民", "配队",
]


def _load_all_entries(game: Game) -> list[dict]:
    """加载游戏全部知识条目（静态角色/武器/圣遗物/料理/材料 + 动态 + 配队）"""
    from app.tools.game_entity import load_entries

    out: list[dict] = []
    for t in ("character", "weapon", "artifact", "food", "material"):
        out.extend(load_entries(game.data_dir, t))
    team_path = game.data_dir / "teams.json"
    if team_path.exists():
        try:
            out.extend(json.loads(team_path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            logger.warning("读取 teams.json 失败")
    return out


def hybrid_retrieve(game: Game, query: str, top_k: int = 4) -> list[dict]:
    """混合检索：① 名称命中（强信号置顶）→ ② 向量召回补充 → ③ 均未命中时关键词/全文兜底

    返回 docs：doc_id / title / content / source / score
    """
    entries = _load_all_entries(game)

    # ① 名称命中（置顶）
    name_hits: list[dict] = []
    for e in entries:
        name = e.get("name", "")
        if name and (name == query or name in query or query in name):
            name_hits.append(e)
            continue
        if e.get("type") == "team" and query in (e.get("name", "") + e.get("summary", "")):
            name_hits.append(e)
    name_docs = [
        {
            "doc_id": e.get("id", ""),
            "title": e.get("name", ""),
            "content": json.dumps({k: v for k, v in e.items() if k != "_meta"}, ensure_ascii=False),
            "source": e.get("source", "static"),
            "score": 1.0,
        }
        for e in name_hits[:3]
    ]

    # ② 向量检索补充
    vec_docs: list[dict] = []
    try:
        vec_docs = retriever.retrieve(game, query, top_k=5)
    except Exception as e:  # noqa: BLE001
        logger.warning("向量检索不可用，仅名称/关键词: %s", e)

    seen = {d["doc_id"] for d in name_docs}
    docs = list(name_docs) + [d for d in vec_docs if d["doc_id"] not in seen]
    docs = docs[:top_k]

    # ③ 元素 × 职能精确补充（如"雷系副C"→ element=雷 且 role 含副C 的角色）
    ELEMENTS = ("火", "水", "雷", "冰", "风", "岩", "草")
    FUNC_WORDS = ("主C", "副C", "辅助", "治疗", "护盾")
    q_els = [w for w in ELEMENTS if w in query]
    q_func = [w for w in FUNC_WORDS if w in query]
    if q_els and q_func:
        extra: list[dict] = []
        for e in entries:
            if e.get("type") != "character" or e.get("id") in seen:
                continue
            role = str(e.get("role", ""))
            if e.get("element") in q_els and any(f in role for f in q_func):
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
