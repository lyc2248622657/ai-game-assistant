# -*- coding: utf-8 -*-
"""组件级消融实验（3.3 修复）

在固定评测集子集上，分别关闭 replan / reflect / 混合检索 / 记忆注入，
与全链路对比四指标，回答"哪个组件真正贡献了效果提升"。

用法（backend 目录）:
    .venv\\Scripts\\python.exe scripts\\eval\\ablation.py --cases 4
    .venv\\Scripts\\python.exe scripts\\eval\\ablation.py --cases 4 --config no_replan,no_reflect
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.agents.graph import app_graph  # noqa: E402
from app.agents.llm import get_chat_model  # noqa: E402
from app.core.logging import get_logger  # noqa: E402
from app.core.usage import usage_stats  # noqa: E402

logger = get_logger(__name__)
EVAL_SET = Path(__file__).resolve().parent / "evaluation_set.json"

CONFIGS = {
    "all": {},
    "no_replan": {"replan": True},
    "no_reflect": {"reflect": True},
    "no_hybrid": {"hybrid": True},
    "no_memory": {"memory": True},
}

JUDGE_PROMPT = (
    "你是智能体回答质量的评审员。给定用户问题、期望要点与智能体的回答（含引用），逐项评分：\n"
    "1) accuracy：核心事实的正确性，0~1 之间的小数（对照期望要点逐条核对，回答与期望要点一致给分，"
    "无法从引用和期望要点核验的内容标为存疑并扣分，禁止使用你自己的游戏知识判断对错）；\n"
    "2) faithfulness：忠实性，回答中的事实是否都有引用/资料支撑、有无编造，0~1；\n"
    "3) coverage：覆盖度，期望要点被回答覆盖的比例，0~1；\n"
    "4) hallucination_count：回答中编造的、资料与引用之外的具体事实数量（整数，没有则为 0）。\n"
    "注意：回答说'资料中未收录/无法确认'是诚实的表现，不算幻觉。\n"
    '只输出 JSON：{"accuracy": 0.0, "faithfulness": 0.0, "coverage": 0.0, "hallucination_count": 0, "comment": "一句话点评"}'
)


def run_case(model, case: dict, ablate: dict) -> dict:
    q = case["question"]
    started = time.time()
    result = app_graph.invoke(
        {
            "game_id": "genshin",
            "session_id": "ablation",
            "user_message": q,
            "messages": [],
            "ablate": ablate,
        }
    )
    answer = result.get("final_answer") or ""
    citations = result.get("citations") or []
    judge = model.invoke(
        [
            {"role": "system", "content": JUDGE_PROMPT},
            {
                "role": "user",
                "content": (
                    f"用户问题：{q}\n\n期望要点：{json.dumps(case['key_points'], ensure_ascii=False)}\n\n"
                    f"智能体回答：{answer}\n\n"
                    f"引用资料：{json.dumps([{'title': c.get('title'), 'content': c.get('content', '')[:600]} for c in citations], ensure_ascii=False)}"
                ),
            },
        ]
    )
    m = re.search(r"\{.*\}", judge.content or "", re.S)
    scores = json.loads(m.group(0)) if m else {}
    return {
        "id": case["id"],
        "answer": answer[:400],
        "scores": {
            "accuracy": float(scores.get("accuracy", 0.0)),
            "faithfulness": float(scores.get("faithfulness", 0.0)),
            "coverage": float(scores.get("coverage", 0.0)),
            "hallucination_count": int(scores.get("hallucination_count", 0)),
        },
        "elapsed": round(time.time() - started, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=4, help="评测集前 N 条（0=全量，token 随条数增长）")
    ap.add_argument("--config", type=str, default=",".join(CONFIGS), help="逗号分隔的配置名（默认全部）")
    ap.add_argument("--out", type=str, default="data/ablation_report.json")
    args = ap.parse_args()

    cases = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    if args.cases > 0:
        cases = cases[: args.cases]
    configs = [c.strip() for c in args.config.split(",") if c.strip() in CONFIGS]
    if not configs:
        print(f"无效配置，可选: {','.join(CONFIGS)}")
        return 1

    model = get_chat_model()
    report: dict = {"cases": len(cases), "configs": {}}
    print(f"消融评测：{len(cases)} 条 × {len(configs)} 配置（约 {len(cases) * len(configs)} 次 Agent 链路 + Judge，耗时较长）")

    for cfg in configs:
        usage_stats.reset()
        results = []
        for case in cases:
            try:
                results.append(run_case(model, case, CONFIGS[cfg]))
            except Exception as e:  # noqa: BLE001
                logger.error("消融用例失败: %s", e)
                results.append({
                    "id": case["id"], "answer": f"<异常:{e}>",
                    "scores": {"accuracy": 0.0, "faithfulness": 0.0, "coverage": 0.0, "hallucination_count": 0},
                    "elapsed": 0.0,
                })
        usage = usage_stats.snapshot()

        def avg(key):
            vals = [r["scores"][key] for r in results]
            return round(sum(vals) / len(vals), 3) if vals else 0.0

        report["configs"][cfg] = {
            "ablate": CONFIGS[cfg],
            "n": len(results),
            "accuracy": avg("accuracy"),
            "faithfulness": avg("faithfulness"),
            "coverage": avg("coverage"),
            "avg_hallucination_count": round(sum(r["scores"]["hallucination_count"] for r in results) / len(results), 2),
            "cases_with_hallucination": sum(1 for r in results if r["scores"]["hallucination_count"] > 0),
            "total_tokens": usage["total_tokens"],
            "llm_calls": usage["llm_calls"],
        }
        print(f"  [{cfg}] 完成：acc={report['configs'][cfg]['accuracy']} fth={report['configs'][cfg]['faithfulness']} "
              f"cov={report['configs'][cfg]['coverage']} hall={report['configs'][cfg]['avg_hallucination_count']} "
              f"tok={usage['total_tokens']:,}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 对比表（以 all 为基准）
    base = report["configs"]["all"] if "all" in report["configs"] else None
    print("\n===== 组件消融对比（以全链路为基准） =====")
    print(f"{'配置':<12s} {'acc':>6s} {'Δacc':>7s} {'fth':>6s} {'Δfth':>7s} {'cov':>6s} {'Δcov':>7s} {'幻觉':>6s} {'token':>8s}")
    for cfg in configs:
        v = report["configs"][cfg]
        if base and cfg != "all":
            d_acc = round(v["accuracy"] - base["accuracy"], 3)
            d_fth = round(v["faithfulness"] - base["faithfulness"], 3)
            d_cov = round(v["coverage"] - base["coverage"], 3)
            print(f"{cfg:<12s} {v['accuracy']:>6.3f} {d_acc:>+7.3f} {v['faithfulness']:>6.3f} {d_fth:>+7.3f} "
                  f"{v['coverage']:>6.3f} {d_cov:>+7.3f} {v['avg_hallucination_count']:>6.2f} {v['total_tokens']:>8,}")
        else:
            print(f"{cfg:<12s} {v['accuracy']:>6.3f} {'—':>7s} {v['faithfulness']:>6.3f} {'—':>7s} "
                  f"{v['coverage']:>6.3f} {'—':>7s} {v['avg_hallucination_count']:>6.2f} {v['total_tokens']:>8,}")
    if base:
        print("\n结论（示例口径）：负 Δ 表示去掉该组件后指标下降 → 组件有正贡献；")
        print("接近 0 表示该组件在当前评测集上贡献有限（可能过度工程）。")
    print(f"\n报告已写入: {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
