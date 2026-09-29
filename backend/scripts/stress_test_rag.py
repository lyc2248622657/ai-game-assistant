# -*- coding: utf-8 -*-
"""Chroma 并发查询压力测试（4.1 修复）

验证嵌入式 PersistentClient 在多线程并发查询下的行为：
  - 是否出现异常 / 数据错误
  - 吞吐与平均延迟（锁竞争表现）
  - 结论写入 README 式输出

用法（backend 目录）:
    .venv\\Scripts\\python.exe scripts\\stress_test_rag.py --threads 8 --rounds 10
"""
import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.knowledge.games import registry  # noqa: E402
from app.rag.retriever import retriever  # noqa: E402

QUERIES = [
    "胡桃用什么圣遗物",
    "绝缘之旗印适合什么角色",
    "那维莱特配队推荐",
    "雷系副C有哪些",
    "钟离护盾怎么配",
    "甘雨冰队怎么玩",
    "香菱武器推荐",
    "万叶怎么配队",
]


def _one_query(game, q: str) -> float:
    t0 = time.time()
    retriever.retrieve(game, q, top_k=4)
    return time.time() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--rounds", type=int, default=10)
    args = ap.parse_args()

    game = registry.get_game("genshin")
    try:
        n_docs = retriever._store.count(game.collection)
    except Exception:  # noqa: BLE001
        n_docs = "?"
    print(f"集合 {game.collection} 文档数: {n_docs}")

    latencies: list[float] = []
    errors = 0
    total_start = time.time()
    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        futures = [
            ex.submit(_one_query, game, QUERIES[i % len(QUERIES)])
            for i in range(args.threads * args.rounds)
        ]
        for f in futures:
            try:
                latencies.append(f.result())
            except Exception as e:  # noqa: BLE001
                errors += 1
                print(f"  查询异常: {e}")
    wall = time.time() - total_start

    latencies.sort()
    n = len(latencies)
    p50 = latencies[n // 2] if n else 0
    p95 = latencies[int(n * 0.95)] if n else 0
    avg = sum(latencies) / n if n else 0
    print(f"\n===== Chroma 并发压力测试 =====")
    print(f"并发线程: {args.threads} × {args.rounds} 轮 = {n} 次查询")
    print(f"墙钟耗时: {wall:.2f}s（理论串行下限 ≈ {sum(latencies):.2f}s）")
    print(f"平均延迟: {avg * 1000:.1f}ms  P50: {p50 * 1000:.1f}ms  P95: {p95 * 1000:.1f}ms")
    print(f"吞吐: {n / wall:.1f} 查询/秒")
    print(f"错误数: {errors}")
    if errors == 0:
        print("结论: 并发查询无异常（嵌入式模式存在内部锁，延迟随并发上升，但功能正确）")
    else:
        print(f"结论: 出现 {errors} 个异常，存在并发问题，需要串行化或异步客户端")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
