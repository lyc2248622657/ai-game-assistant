# -*- coding: utf-8 -*-
"""调试：查看火系配队查询的原始 top10 相似度"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.knowledge.games import registry  # noqa: E402
from app.rag.embedding import get_embedding  # noqa: E402
from app.rag.vectorstore import get_vectorstore  # noqa: E402

game = registry.get_game("genshin")
emb = get_embedding()
store = get_vectorstore()
q = "推荐一个火系主C的配队"
q_vec = emb.encode([q])[0]
results = store.query(game.collection, q_vec, top_k=10)
for r in results:
    print(round(1.0 - r["distance"], 4), (r["metadata"] or {}).get("title"), (r["metadata"] or {}).get("type"))
