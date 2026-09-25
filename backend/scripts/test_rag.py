# -*- coding: utf-8 -*-
"""验证 RAG 向量检索召回质量"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.knowledge.games import registry  # noqa: E402
from app.rag.retriever import retriever  # noqa: E402

game = registry.get_game("genshin")
for q in ["推荐一个火系主C的配队", "胡桃用什么圣遗物", "雷系副C有哪些角色", "钟离是几星"]:
    docs = retriever.retrieve(game, q, top_k=3)
    print(f"Q: {q}")
    for d in docs:
        print(f'  - {d["title"]} (score={d["score"]}, src={d["source"]})')
    print()
