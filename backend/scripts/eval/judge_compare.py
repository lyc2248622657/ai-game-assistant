# -*- coding: utf-8 -*-
"""回答质量对比：对 compare_react 的 LangGraph / 自研 ReAct 回答用同一 Judge 打分

用法（backend 目录）:
    .venv\\Scripts\\python.exe scripts\\eval\\judge_compare.py [--out data/judge_compare.json]
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.agents.llm import get_chat_model  # noqa: E402
from app.core.usage import usage_stats  # noqa: E402

JUDGE_PROMPT = (
    "你是智能体回答质量的评审员。给定用户问题、期望要点、智能体回答与回答所依据的资料（工具返回），逐项评分：\n"
    "1) accuracy：核心事实的正确性，0~1（对照期望要点逐条核对；无法核验的内容标为存疑并扣分，"
    "禁止使用你自己的游戏知识判断对错）；\n"
    "2) faithfulness：忠实性，回答中的事实是否都能在『回答依据资料』中找到依据、有无编造，0~1；\n"
    "3) coverage：覆盖度，期望要点被回答覆盖的比例，0~1；\n"
    "4) hallucination_count：回答中编造的、无依据的具体事实数量（整数，没有则为 0）。\n"
    "注意：回答说『资料中未收录/无法确认』是诚实的表现，不算幻觉；"
    "回答内容与『回答依据资料』一致即视为有依据，不得凭你自己的游戏知识认定编造；"
    "『与游戏常识不符』的判断必须来自期望要点，不得使用你自己的游戏知识。\n"
    '只输出 JSON：{"accuracy": 0.0, "faithfulness": 0.0, "coverage": 0.0, "hallucination_count": 0, "comment": "一句话点评"}'
)

# 与评测集 key_points 对齐的期望要点（6 条对比用例）
KEY_POINTS = {
    "胡桃是几星角色？": ["胡桃", "5星"],
    "介绍一下奥黛塔": ["奥黛塔", "冰", "单手剑", "至冬", "7.0"],
    "胡桃用什么圣遗物？": ["炽烈的炎之魔女", "胡桃", "火系"],
    "炽烈的炎之魔女适合什么角色？": ["炽烈的炎之魔女", "胡桃", "火系"],
    "雷系副C有哪些？": ["雷系", "副C", "雷电将军"],
    "护摩之杖适合哪个角色？": ["护摩之杖", "胡桃", "钟离", "香菱"],
}


def score(model, question: str, answer: str, citations: list[dict] | None = None) -> dict:
    evidence = ""
    if citations:
        evidence = "\n\n回答依据资料（智能体实际使用的工具返回）：\n" + json.dumps(
            [{"title": c.get("title", ""), "content": c.get("content", "")[:600]} for c in citations[:5]],
            ensure_ascii=False,
        )
    resp = model.invoke(
        [
            {"role": "system", "content": JUDGE_PROMPT},
            {
                "role": "user",
                "content": (
                    f"用户问题：{question}\n\n期望要点：{json.dumps(KEY_POINTS.get(question, []), ensure_ascii=False)}\n\n"
                    f"智能体回答：{answer[:1200]}{evidence}"
                ),
            },
        ]
    )
    m = re.search(r"\{.*\}", resp.content or "", re.S)
    d = json.loads(m.group(0)) if m else {}
    return {
        "accuracy": float(d.get("accuracy", 0.0)),
        "faithfulness": float(d.get("faithfulness", 0.0)),
        "coverage": float(d.get("coverage", 0.0)),
        "hallucination_count": int(d.get("hallucination_count", 0)),
        "comment": d.get("comment", ""),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=str, default="data/judge_compare.json")
    args = ap.parse_args()
    src = Path(__file__).resolve().parent.parent.parent / "data" / "compare_react.json"
    cases = json.loads(src.read_text(encoding="utf-8"))

    usage_stats.reset()
    model = get_chat_model()
    rows = []
    for c in cases:
        q = c["question"]
        g = score(model, q, c["graph"]["answer"])
        r = score(model, q, c["react"]["answer"], c["react"].get("citations") or [])
        rows.append({"question": q, "graph": g, "react": r})
        print(f"\n=== {q} ===")
        print(f"  LangGraph: acc={g['accuracy']} fth={g['faithfulness']} cov={g['coverage']} hall={g['hallucination_count']} | {g['comment'][:40]}")
        print(f"  自研ReAct: acc={r['accuracy']} fth={r['faithfulness']} cov={r['coverage']} hall={r['hallucination_count']} | {r['comment'][:40]}")

    def avg(key, impl):
        return round(sum(row[impl][key] for row in rows) / len(rows), 3)

    print("\n===== 平均 =====")
    for impl in ("graph", "react"):
        print(f"  {impl:5s}: acc={avg('accuracy', impl)} fth={avg('faithfulness', impl)} "
              f"cov={avg('coverage', impl)} hall={round(sum(r[impl]['hallucination_count'] for r in rows) / len(rows), 2)}")
    usage = usage_stats.snapshot()
    print(f"  Judge 调用 {usage['llm_calls']} 次，token {usage['total_tokens']}")

    report = {"rows": rows, "summary": {
        impl: {"accuracy": avg("accuracy", impl), "faithfulness": avg("faithfulness", impl),
               "coverage": avg("coverage", impl),
               "avg_hallucination": round(sum(r[impl]["hallucination_count"] for r in rows) / len(rows), 2)}
        for impl in ("graph", "react")
    }, "usage": usage}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入: {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
