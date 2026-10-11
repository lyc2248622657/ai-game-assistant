# -*- coding: utf-8 -*-
"""LLM-as-Judge 评测运行器：跑完整 Agent 图 → 按四指标打分 → 汇总报告

用法（backend 目录）:
    .venv\\Scripts\\python.exe scripts\\eval\\eval_runner.py --limit 5
    .venv\\Scripts\\python.exe scripts\\eval\\eval_runner.py --out data/eval_report.json

指标：
  accuracy          回答中核心事实的正确性（对照 key_points）
  faithfulness      忠实性：回答内容是否都能由引用/资料支撑（不编造）
  coverage          覆盖度：key_points 中被回答覆盖的比例
  hallucination     幻觉：回答中编造的、资料外的事实条数
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.agents.graph import app_graph  # noqa: E402
from app.agents.llm import get_chat_model  # noqa: E402
from app.core.logging import get_logger  # noqa: E402
from app.core.usage import usage_stats  # noqa: E402
from scripts.eval.eval_common import mean_ci, pass_rate  # noqa: E402

logger = get_logger(__name__)
EVAL_DIR = Path(__file__).resolve().parent
GENSHIN_SET = EVAL_DIR / "evaluation_set.json"
ARKNIGHTS_SET = EVAL_DIR / "arknights_evaluation_set.json"

# 期望要点中的"元指令"词（不计入 RAG 命中统计）
STOP_WORDS = {
    "不编造", "以资料为准或如实说明", "如实说明或给出依据", "无资料时如实说明",
    "对比", "各自特点", "理由", "推荐", "最近实装", "配队", "深渊", "四星",
}


def _load_cases(game: str) -> list[dict]:
    """按 --game 加载评测集：genshin=原神 30 题，arknights=方舟 20 题，all=合并 50 题"""
    g = (game or "all").lower()
    sets: list[tuple[Path, str]] = []
    if g in ("genshin", "all"):
        sets.append((GENSHIN_SET, "genshin"))
    if g in ("arknights", "all"):
        sets.append((ARKNIGHTS_SET, "arknights"))
    cases: list[dict] = []
    for path, gid in sets:
        data = json.loads(path.read_text(encoding="utf-8"))
        for c in data:
            c["game_id"] = c.get("game_id") or gid
            cases.append(c)
    logger.info("评测集加载: game=%s 共 %d 条", g, len(cases))
    return cases

JUDGE_PROMPT = (
    "你是智能体回答质量的评审员。给定用户问题、期望要点与智能体的回答（含引用），逐项评分：\n"
    "1) accuracy：核心事实的正确性，0~1 之间的小数（对照期望要点逐条核对，回答与期望要点一致给分，"
    "无法从引用和期望要点核验的内容标为存疑并扣分，禁止使用你自己的游戏知识判断对错）；\n"
    "2) faithfulness：忠实性，回答中的事实是否都有引用/资料支撑、有无编造，0~1；\n"
    "3) coverage：覆盖度，期望要点被回答覆盖的比例，0~1；\n"
    "4) hallucination_count：回答中编造的、资料与引用之外的具体事实数量（整数，没有则为 0）。\n"
    "注意：回答说'资料中未收录/无法确认'是诚实的表现，不算幻觉；"
    "回答给出了期望要点之外的合理建议不算错误；"
    "『与游戏常识不符』的判断必须来自引用或期望要点，不得使用你自己的游戏知识。\n"
    '只输出 JSON：{"accuracy": 0.0, "faithfulness": 0.0, "coverage": 0.0, "hallucination_count": 0, "comment": "一句话点评"}'
)


def run_case(model, case: dict) -> dict:
    """跑单条：Agent 图 → Judge 打分"""
    q = case["question"]
    started = time.time()
    result = app_graph.invoke(
        {
            "game_id": case.get("game_id", "genshin"),
            "session_id": "eval",
            "user_message": q,
            "messages": [],
        }
    )
    answer = result.get("final_answer") or ""
    citations = result.get("citations") or []
    reflect = result.get("self_reflect") or {}

    judge = model.invoke(
        [
            {"role": "system", "content": JUDGE_PROMPT},
            {
                "role": "user",
                "content": (
                    f"用户问题：{q}\n\n期望要点：{json.dumps(case['key_points'], ensure_ascii=False)}\n\n"
                    f"智能体回答：{answer}\n\n"
                    f"引用资料：{json.dumps([{'title': c.get('title'), 'content': c.get('content', '')[:4000]} for c in citations], ensure_ascii=False)}"
                ),
            },
        ]
    )
    import re

    m = re.search(r"\{.*\}", judge.content or "", re.S)
    scores = json.loads(m.group(0)) if m else {}
    elapsed = round(time.time() - started, 1)

    # RAG 命中指标：期望要点中的实体/概念词是否出现在引用资料（title + content 前 4000 字）
    kp_names = [k for k in case["key_points"] if len(k) > 1 and k not in STOP_WORDS]
    docs_text = " ".join(
        f"{c.get('title', '')} {str(c.get('content', ''))[:4000]}"
        for c in citations
    )
    retrieval_hit = round(
        sum(1 for k in kp_names if k in docs_text) / len(kp_names), 3
    ) if kp_names else 1.0

    return {
        "id": case["id"],
        "type": case["type"],
        "game_id": case.get("game_id", "genshin"),
        "question": q,
        "answer": answer[:500],
        "citations": [
            {"title": c["title"], "content": str(c.get("content", ""))[:4000]}
            for c in citations
        ][:5],  # 3.2 修复：保留引用正文，Judge 可依据引用内容核验（否则误判"无引用支撑"）；4.x 实体含技能/命座，截断放宽至 4000
        "retrieval_hit": retrieval_hit,
        "reflect_passed": reflect.get("passed"),
        "reflect_issues": reflect.get("issues", []),
        "scores": {
            "accuracy": float(scores.get("accuracy", 0.0)),
            "faithfulness": float(scores.get("faithfulness", 0.0)),
            "coverage": float(scores.get("coverage", 0.0)),
            "hallucination_count": int(scores.get("hallucination_count", 0)),
        },
        "comment": scores.get("comment", ""),
        "elapsed": elapsed,
    }


def _load_previous(out_path: Path) -> dict | None:
    """读取上一次评测报告（用于 --only-failed 与 token 增量对比）"""
    if out_path.is_file():
        try:
            return json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0=全量）")
    ap.add_argument("--out", type=str, default="data/eval_report.json")
    ap.add_argument("--game", type=str, default="all", choices=["genshin", "arknights", "all"],
                    help="评测目标游戏：genshin=原神 / arknights=方舟 / all=两者（默认）")
    ap.add_argument("--only-failed", action="store_true",
                    help="只重跑上次报告中的失败/低分/含幻觉用例（增量回归，省 token）")
    args = ap.parse_args()

    cases = _load_cases(args.game)
    out_path = Path(args.out)
    if args.only_failed:
        prev = _load_previous(out_path)
        if not prev:
            logger.warning("无上次报告可对比，退化为全量运行")
        else:
            bad_ids = {
                r["id"]
                for r in prev.get("cases", [])
                if r["scores"]["accuracy"] < 0.8
                or r["scores"]["hallucination_count"] > 0
                # reflect_passed=False 仅是"触发过回炉"（质量机制已修正），Judge 分数才是最终标准，不单列入失败
            }
            cases = [c for c in cases if c["id"] in bad_ids]
            logger.info("增量模式：上次 %d 条中 %d 条需重跑", len(prev.get("cases", [])), len(cases))
    if args.limit > 0:
        cases = cases[: args.limit]
    if not cases:
        print("没有需要运行的用例（全量通过或 limit 截断），跳过")
        return 0
    logger.info("评测集 %d 条，开始…（每条含 Agent 链路 + Judge，约需 10~30s）", len(cases))

    # token 统计：本轮归零，跑完取快照写入报告
    usage_stats.reset()
    model = get_chat_model()
    results = []
    for i, case in enumerate(cases, 1):
        logger.info("[%d/%d] %s | %s", i, len(cases), case["id"], case["question"])
        try:
            results.append(run_case(model, case))
        except Exception as e:  # noqa: BLE001
            logger.error("用例失败: %s", e)
            results.append({
                "id": case["id"], "type": case["type"], "question": case["question"],
                "answer": f"<运行异常: {e}>", "citations": [], "reflect_passed": None,
                "reflect_issues": [], "scores": {"accuracy": 0.0, "faithfulness": 0.0,
                                                  "coverage": 0.0, "hallucination_count": 0},
                "comment": "运行异常", "elapsed": 0.0,
            })
    usage = usage_stats.snapshot()

    # 汇总（3.1 修复：均值 + 95% 置信区间 + 阈值通过率 Wilson CI）
    def avg(key):
        vals = [r["scores"][key] for r in results if r["scores"].get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else 0.0

    metric_vals = {
        k: [r["scores"][k] for r in results]
        for k in ("accuracy", "faithfulness", "coverage")
    }
    ci = {k: mean_ci(vals) for k, vals in metric_vals.items()}

    summary = {
        "total": len(results),
        "games": sorted({r.get("game_id", "genshin") for r in results}),
        "metrics": {
            "accuracy": avg("accuracy"),
            "faithfulness": avg("faithfulness"),
            "coverage": avg("coverage"),
            "retrieval_hit": round(sum(r.get("retrieval_hit", 1.0) for r in results) / len(results), 3),
            "avg_hallucination_count": round(sum(r["scores"]["hallucination_count"] for r in results) / len(results), 2),
            "cases_with_hallucination": sum(1 for r in results if r["scores"]["hallucination_count"] > 0),
            "reflect_triggered": sum(1 for r in results if r["reflect_passed"] is False),
        },
        "confidence_intervals": {
            k: {"mean": ci[k][0], "ci_lo": ci[k][1], "ci_hi": ci[k][2]}
            for k in ("accuracy", "faithfulness", "coverage")
        },
        "pass_rates": {
            "accuracy_pass": pass_rate(metric_vals["accuracy"], 0.8),
            "faithfulness_pass": pass_rate(metric_vals["faithfulness"], 0.8),
            "coverage_pass": pass_rate(metric_vals["coverage"], 0.8),
            "retrieval_hit_pass": pass_rate([r.get("retrieval_hit", 1.0) for r in results], 0.8),
            "no_hallucination": pass_rate([0 if v > 0 else 1 for v in metric_vals.get("coverage", []) or
                                          [r["scores"]["hallucination_count"] for r in results]], 1.0),
        },
        "usage": {
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "total_tokens": usage["total_tokens"],
            "llm_calls": usage["llm_calls"],
            "avg_tokens_per_case": round(usage["total_tokens"] / len(results), 0) if results else 0,
        },
        "by_type": {},
    }
    for t in ("entity", "knowledge", "edge", "complex"):
        rs = [r for r in results if r["type"] == t]
        if rs:
            summary["by_type"][t] = {
                "n": len(rs),
                "accuracy": round(sum(r["scores"]["accuracy"] for r in rs) / len(rs), 3),
                "faithfulness": round(sum(r["scores"]["faithfulness"] for r in rs) / len(rs), 3),
                "coverage": round(sum(r["scores"]["coverage"] for r in rs) / len(rs), 3),
            }

    # token 增量对比（与上一份报告）
    prev_report = _load_previous(out_path)
    if prev_report and "usage" in prev_report:
        prev_usage = prev_report["usage"]
        summary["usage"]["prev_total_tokens"] = prev_usage.get("total_tokens", 0)
        summary["usage"]["delta_tokens_vs_prev"] = usage["total_tokens"] - prev_usage.get("total_tokens", 0)

    report = {"summary": summary, "cases": results}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 控制台表格
    print("\n===== LLM-as-Judge 评测报告 =====")
    print(f"总条数: {summary['total']}（游戏: {'+'.join(summary['games'])}）")
    ci_show = summary["confidence_intervals"]
    pr = summary["pass_rates"]
    print(f"准确率 accuracy      : {ci_show['accuracy']['mean']}  (95%CI {ci_show['accuracy']['ci_lo']}~{ci_show['accuracy']['ci_hi']}, "
          f"通过率 {pr['accuracy_pass']['rate']} [{pr['accuracy_pass']['ci_lo']}~{pr['accuracy_pass']['ci_hi']}])")
    print(f"忠实性 faithfulness  : {ci_show['faithfulness']['mean']}  (95%CI {ci_show['faithfulness']['ci_lo']}~{ci_show['faithfulness']['ci_hi']}, "
          f"通过率 {pr['faithfulness_pass']['rate']} [{pr['faithfulness_pass']['ci_lo']}~{pr['faithfulness_pass']['ci_hi']}])")
    print(f"覆盖度 coverage      : {ci_show['coverage']['mean']}  (95%CI {ci_show['coverage']['ci_lo']}~{ci_show['coverage']['ci_hi']}, "
          f"通过率 {pr['coverage_pass']['rate']} [{pr['coverage_pass']['ci_lo']}~{pr['coverage_pass']['ci_hi']}])")
    print(f"RAG 命中 retrieval   : {summary['metrics']['retrieval_hit']}（通过率 {pr['retrieval_hit_pass']['rate']}）")
    print(f"平均幻觉条数         : {summary['metrics']['avg_hallucination_count']}（{summary['metrics']['cases_with_hallucination']} 条含幻觉，"
          f"无幻觉率 {pr['no_hallucination']['rate']} [{pr['no_hallucination']['ci_lo']}~{pr['no_hallucination']['ci_hi']}]）")
    print(f"Reflection 触发回炉  : {summary['metrics']['reflect_triggered']} 条")
    u = summary["usage"]
    print(f"Token 消耗           : {u['total_tokens']:,}（输入 {u['input_tokens']:,} / 输出 {u['output_tokens']:,}，"
          f"{u['llm_calls']} 次调用，平均 {u['avg_tokens_per_case']:,}/条）")
    if "delta_tokens_vs_prev" in u:
        print(f"  对比上次            : {u['prev_total_tokens']:,} → {u['total_tokens']:,}"
              f"（{'节省' if u['delta_tokens_vs_prev'] < 0 else '增加'} {abs(u['delta_tokens_vs_prev']):,}）")
    print("按类型：")
    for t, v in summary["by_type"].items():
        print(f"  {t:10s} n={v['n']:2d} acc={v['accuracy']} fth={v['faithfulness']} cov={v['coverage']}")
    print("\n失败/低分用例（accuracy<0.8 或含幻觉 或 RAG 未命中）：")
    for r in results:
        s = r["scores"]
        if s["accuracy"] < 0.8 or s["hallucination_count"] > 0 or r.get("retrieval_hit", 1.0) < 0.8:
            print(f"  {r['id']} [{r['type']}/{r.get('game_id')}] acc={s['accuracy']} hall={s['hallucination_count']} "
                  f"hit={r.get('retrieval_hit')} reflect_pass={r['reflect_passed']} | {r['question'][:30]} | {r['comment'][:40]}")
    print(f"\n报告已写入: {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
