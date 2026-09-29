# -*- coding: utf-8 -*-
"""LLM-as-Judge 校准分析（3.2 修复）

流程：读取上一份 eval_report.json 中的真实回答 → 对 calibration_set.json 里
人工标注的用例，用 Judge（与生成同模型，默认 DeepSeek）重新打分 →
对比人工评分，输出：
  - 每指标平均绝对误差（MAE）
  - 一致性（|diff|<=0.2 视为一致）的比例
  - 偏差模式诊断：系统性偏高/偏低（均值差）、长度偏好（judge 分与回答长度相关性）

用法（backend 目录）:
    .venv\\Scripts\\python.exe scripts\\eval\\judge_calibration.py
    .venv\\Scripts\\python.exe scripts\\eval\\judge_calibration.py --report data/eval_report.json --cal scripts/eval/calibration_set.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.agents.llm import get_chat_model  # noqa: E402
from app.core.logging import get_logger  # noqa: E402

logger = get_logger(__name__)

JUDGE_PROMPT = (
    "你是智能体回答质量的评审员。给定用户问题、期望要点与智能体的回答（含引用），逐项评分：\n"
    "1) accuracy：核心事实的正确性，0~1 之间的小数（对照期望要点逐条核对，回答与期望要点一致给分，"
    "无法从引用和期望要点核验的内容标为存疑并扣分，禁止使用你自己的游戏知识判断对错）；\n"
    "2) faithfulness：忠实性，回答中的事实是否都有引用/资料支撑、有无编造，0~1；\n"
    "3) coverage：覆盖度，期望要点被回答覆盖的比例，0~1；\n"
    "4) hallucination_count：回答中编造的、资料与引用之外的具体事实数量（整数，没有则为 0）。\n"
    "注意：回答说'资料中未收录/无法确认'是诚实的表现，不算幻觉；"
    "'与游戏常识不符'的判断必须来自引用或期望要点，不得使用你自己的游戏知识。\n"
    '只输出 JSON：{"accuracy": 0.0, "faithfulness": 0.0, "coverage": 0.0, "hallucination_count": 0, "comment": "一句话点评"}'
)

METRICS = ("accuracy", "faithfulness", "coverage", "hallucination_count")


def _fmt_citations(citations) -> list[dict]:
    """eval 报告中 citations 可能是字符串列表（标题）或 dict 列表，统一为 judge 输入格式"""
    out = []
    for c in citations or []:
        if isinstance(c, str):
            out.append({"title": c, "content": ""})
        else:
            out.append({"title": c.get("title", ""), "content": str(c.get("content", ""))[:600]})
    return out


def _judge_score(model, question: str, key_points, answer: str, citations: list) -> dict:
    resp = model.invoke(
        [
            {"role": "system", "content": JUDGE_PROMPT},
            {
                "role": "user",
                "content": (
                    f"用户问题：{question}\n\n期望要点：{json.dumps(key_points, ensure_ascii=False)}\n\n"
                    f"智能体回答：{answer}\n\n"
                    f"引用资料：{json.dumps(_fmt_citations(citations), ensure_ascii=False)}"
                ),
            },
        ]
    )
    m = re.search(r"\{.*\}", resp.content or "", re.S)
    scores = json.loads(m.group(0)) if m else {}
    return {
        "accuracy": float(scores.get("accuracy", 0.0)),
        "faithfulness": float(scores.get("faithfulness", 0.0)),
        "coverage": float(scores.get("coverage", 0.0)),
        "hallucination_count": int(scores.get("hallucination_count", 0)),
        "comment": scores.get("comment", ""),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=str, default="data/eval_report.json")
    ap.add_argument("--cal", type=str, default="scripts/eval/calibration_set.json")
    args = ap.parse_args()

    report_path = Path(args.report)
    cal_path = Path(args.cal)
    if not report_path.is_file():
        print(f"未找到评测报告 {report_path}，请先运行 eval_runner.py 生成报告")
        return 1
    if not cal_path.is_file():
        print(f"未找到校准集 {cal_path}")
        return 1

    report = json.loads(report_path.read_text(encoding="utf-8"))
    cal = json.loads(cal_path.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in report.get("cases", [])}

    model = get_chat_model()
    eval_set = json.loads(
        (Path(__file__).resolve().parent / "evaluation_set.json").read_text(encoding="utf-8")
    )
    eval_by_id = {c["id"]: c for c in eval_set}

    rows = []
    for item in cal["cases"]:
        cid = item["case_id"]
        r = by_id.get(cid)
        if r is None:
            logger.warning("报告缺少用例 %s（跳过校准条目）", cid)
            continue
        key_points = eval_by_id.get(cid, {}).get("key_points", [])
        judge = _judge_score(
            model, r["question"], key_points, r["answer"], r.get("citations", [])
        )
        human = item["human_scores"]
        rows.append({"id": cid, "human": human, "judge": judge, "answer_len": len(r["answer"])})

    if not rows:
        print("校准集与报告无交集，请先运行 eval_runner 覆盖对应用例")
        return 1

    print("\n===== Judge 校准分析 =====")
    print(f"校准用例数: {len(rows)}（Judge 模型 = 生成模型 = {model.model_name if hasattr(model, 'model_name') else 'DeepSeek'}）")
    for m in METRICS:
        diffs = []
        for r in rows:
            if m == "hallucination_count":
                d = abs(r["human"][m] - r["judge"][m])
            else:
                d = abs(r["human"][m] - r["judge"][m])
            diffs.append(d)
        mae = round(sum(diffs) / len(diffs), 3)
        consist = round(sum(1 for d in diffs if d <= 0.2) / len(diffs), 3)
        mean_diff = round(sum(
            (r["judge"][m] - r["human"][m]) for r in rows
        ) / len(rows), 3) if m != "hallucination_count" else round(sum(
            (r["judge"][m] - r["human"][m]) for r in rows
        ) / len(rows), 3)
        print(f"  {m:22s} MAE={mae}  一致率(≤0.2)={consist}  平均偏差(judge-human)={mean_diff:+}")
        if m in ("accuracy", "faithfulness", "coverage") and mean_diff > 0.05:
            print(f"      ↑ 系统性偏高 {mean_diff:+.3f}（Judge 偏向给更高分，注意长度偏好/自偏好偏差）")
        if m in ("accuracy", "faithfulness", "coverage") and mean_diff < -0.05:
            print(f"      ↓ 系统性偏低 {mean_diff:+.3f}")

    # 长度偏好诊断：judge 打分与回答长度的 Spearman 秩相关（粗检验）
    n = len(rows)
    if n >= 3:
        lens = sorted((r["answer_len"], r["id"]) for r in rows)
        ranks = {r["id"]: i + 1 for i, (_, cid) in enumerate(lens)}
        accs = sorted((r["judge"]["accuracy"], r["id"]) for r in rows)
        acc_ranks = {r["id"]: i + 1 for i, (_, cid) in enumerate(accs)}
        d2 = sum((ranks[cid] - acc_ranks[cid]) ** 2 for r in rows for cid in [r["id"]])
        rho = 1 - 6 * d2 / (n * (n * n - 1))
        print(f"  长度-accuracy 秩相关 ρ={rho:+.3f}（>0.3 提示长度偏好风险）")
    else:
        print("  校准用例不足 3 条，跳过长度偏好诊断")

    print("\n逐条明细：")
    for r in rows:
        h, j = r["human"], r["judge"]
        print(f"  {r['id']:10s} len={r['answer_len']:4d} | human acc={h['accuracy']} fth={h['faithfulness']} cov={h['coverage']} hall={h['hallucination_count']}")
        print(f"            | judge acc={j['accuracy']} fth={j['faithfulness']} cov={j['coverage']} hall={j['hallucination_count']} | {j['comment'][:40]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
