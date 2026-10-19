"""检索质量评测：golden set → hit@k / MRR。

为什么需要它
------------
在加 rerank、调 top_k、改 RRF 权重之前，必须先能回答"这次改动是变好还是变坏"。
这个脚本不调用任何 LLM：只跑 `hybrid_retrieve`，算检索层的命中情况，因此便宜、可进 CI。

指标
----
- hit@k  ：期望文档（任一）出现在前 k 条里 → 1，否则 0
- MRR    ：第一条命中的排名的倒数（越接近 1 越好）

用法
----
    .venv\\Scripts\\python.exe scripts\\eval\\retrieval_eval.py              # 全量（含向量路）
    .venv\\Scripts\\python.exe scripts\\eval\\retrieval_eval.py --no-vector  # 只跑名称+BM25（不加载模型）
    .venv\\Scripts\\python.exe scripts\\eval\\retrieval_eval.py --k 5 --json data/retrieval_report.json

说明：`--no-vector` 用来在没有 embedding 模型的环境（CI / 新机器）里跑回归；
两者分数不可直接对比（口径不同），报告里会标注 mode。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.core.logging import get_logger, setup_logging  # noqa: E402
from app.knowledge.games import registry  # noqa: E402
from app.rag.retriever import hybrid_retrieve, retriever  # noqa: E402

setup_logging()
logger = get_logger("retrieval-eval")

SET_PATH = Path(__file__).resolve().parent / "retrieval_golden.json"


def _norm(s: str) -> str:
    return str(s or "").strip().lower()


def evaluate(cases: list[dict], top_k: int, no_vector: bool) -> dict:
    rows: list[dict] = []
    per_kind: dict[str, list[dict]] = defaultdict(list)

    for case in cases:
        game = registry.get_game(case["game_id"], require_enabled=False)
        try:
            docs = hybrid_retrieve(game, case["query"], top_k=top_k)
        except Exception as e:  # noqa: BLE001
            logger.error("检索失败 %s: %s", case["id"], e)
            docs = []
        titles = [_norm(d.get("title")) for d in docs]
        expect = [_norm(x) for x in case.get("expect") or []]

        rank = next((i + 1 for i, t in enumerate(titles) if t in expect), None)
        row = {
            "id": case["id"],
            "query": case["query"],
            "kind": case.get("kind", "name"),
            "expect": case.get("expect"),
            "got": [d.get("title") for d in docs],
            "hit": rank is not None,
            "rank": rank,
        }
        rows.append(row)
        per_kind[row["kind"]].append(row)

    def agg(rs: list[dict]) -> dict:
        n = len(rs) or 1
        return {
            "n": len(rs),
            "hit@k": round(sum(1 for r in rs if r["hit"]) / n, 3),
            "mrr": round(sum(1 / r["rank"] for r in rs if r["hit"]) / n, 3),
        }

    return {
        "mode": "no-vector" if no_vector else "hybrid",
        "k": top_k,
        "overall": agg(rows),
        "by_kind": {k: agg(v) for k, v in per_kind.items()},
        "misses": [r for r in rows if not r["hit"]],
        "cases": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="检索质量评测（hit@k / MRR）")
    ap.add_argument("--set", default=str(SET_PATH), help="golden set 路径")
    ap.add_argument("--k", type=int, default=5, help="top_k")
    ap.add_argument("--no-vector", action="store_true", help="跳过向量路（不加载 embedding 模型）")
    ap.add_argument("--json", default="", help="把完整报告写到该路径")
    ap.add_argument("--min-hit", type=float, default=0.0, help="hit@k 低于该值时以非零码退出（CI 用）")
    args = ap.parse_args()

    data = json.loads(Path(args.set).read_text(encoding="utf-8"))
    cases = data.get("cases") or []
    if not cases:
        logger.error("golden set 为空: %s", args.set)
        return 1

    if args.no_vector:
        # 把向量单例替换成恒空：hybrid_retrieve 会记录 warning 后走名称+BM25
        retriever.retrieve = lambda *a, **k: []  # type: ignore[assignment]

    report = evaluate(cases, args.k, args.no_vector)

    print(f"\n检索评测 · mode={report['mode']} · k={report['k']} · 用例 {report['overall']['n']}")
    print(f"  hit@{report['k']} = {report['overall']['hit@k']:.3f}   MRR = {report['overall']['mrr']:.3f}")
    for kind, s in report["by_kind"].items():
        print(f"    - {kind:9} n={s['n']:2}  hit@{report['k']}={s['hit@k']:.3f}  MRR={s['mrr']:.3f}")

    if report["misses"]:
        print(f"\n未命中 {len(report['misses'])} 条（用于定位召回问题）：")
        for m in report["misses"]:
            print(f"  ✗ {m['id']}: {m['query']!r}  期望={m['expect']}  实际top3={m['got'][:3]}")
    else:
        print("\n全部命中 ✓")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已写入 {out}")

    if args.min_hit and report["overall"]["hit@k"] < args.min_hit:
        logger.error(
            "hit@%d=%.3f 低于阈值 %.3f，判定为检索回归", args.k, report["overall"]["hit@k"], args.min_hit
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
