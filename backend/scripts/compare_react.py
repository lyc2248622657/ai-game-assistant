"""框架对比测试：LangGraph 状态图 vs 自研 ReAct 循环

同一组代表性问题上分别运行两条 Agent 实现，对比：
  - 耗时（wall time）
  - token 消耗（ReAct 精确统计；Graph 多节点调用近似合计）
  - 回答质量（LLM-as-Judge 简评 or 人工判读）

用法：.venv\\Scripts\\python.exe scripts\\compare_react.py [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 根入 sys.path

from app.agents.graph import app_graph
from app.agents.scratch_react import scratch_react
from app.agents.state import initial_state
from app.core.logging import get_logger

logger = get_logger(__name__)

QUESTIONS = [
    "胡桃是几星角色？",
    "介绍一下奥黛塔",
    "胡桃用什么圣遗物？",
    "炽烈的炎之魔女适合什么角色？",
    "雷系副C有哪些？",
    "护摩之杖适合哪个角色？",
]


def run_graph(game_id: str, q: str) -> dict:
    state = initial_state(game_id=game_id, session_id=None, user_message=q, messages=[])
    t0 = time.perf_counter()
    result = app_graph.invoke(state)
    return {
        "answer": result.get("final_answer", ""),
        "wall_time_s": round(time.perf_counter() - t0, 2),
        "citations": len(result.get("citations", [])),
        "reflect": (result.get("self_reflect") or {}).get("passed"),
    }


def run_react(game_id: str, q: str) -> dict:
    return scratch_react.run(game_id, q)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=len(QUESTIONS))
    ap.add_argument("--out", default="data/compare_react.json")
    args = ap.parse_args()

    cases = QUESTIONS[: args.limit]
    results = []
    for q in cases:
        g = run_graph("genshin", q)
        r = run_react("genshin", q)
        results.append({"question": q, "graph": g, "react": r})
        print(f"\n=== {q} ===")
        print(f"[LangGraph] {g['wall_time_s']}s / citations={g['citations']} / reflect_pass={g['reflect']}")
        print(f"  -> {g['answer'][:120]}")
        print(f"[自研ReAct] {r['wall_time_s']}s / steps={r['steps']} / tokens={r['usage']['total_tokens']}")
        print(f"  -> {r['answer'][:120]}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已写入 {args.out}")


if __name__ == "__main__":
    main()
