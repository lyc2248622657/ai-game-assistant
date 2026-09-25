# -*- coding: utf-8 -*-
"""对话链路冒烟测试：验证「询问实体 → 工具 → 只回答该实体」

用例：
  1. 奥黛塔（未缓存新角色 → 动态生成 + wiki 验证 + 缓存）【已缓存则直接命中】
  2. 胡桃（静态库命中 → 回答胡桃）
  3. 普通知识问题（配队 → 走检索）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.graph import app_graph  # noqa: E402
from app.agents.state import initial_state  # noqa: E402


def run_case(label: str, message: str, game_id: str = "genshin", session_id: str = "smoke"):
    print("\n" + "=" * 70)
    print(f"用例: {label} | 问题: {message}")
    print("=" * 70)
    state = initial_state(game_id, session_id, message, [])
    result = app_graph.invoke(state)
    print(f"task_type: {result.get('task_type')}")
    print(f"plan: {result.get('plan')}")
    trs = result.get("tool_results", [])
    for tr in trs:
        res = tr.get("result", {})
        name = (res.get("entity") or {}).get("name") if isinstance(res, dict) else "?"
        print(f"工具调用: {tr['name']} → {name} | found={res.get('found') if isinstance(res, dict) else '?'}")
    rd = result.get("retrieved_docs", [])
    if rd:
        print(f"检索命中: {[d['title'] for d in rd]}")
    print(f"引用: {[c['title'] for c in result.get('citations', [])]}")
    ans = result.get("final_answer") or ""
    print(f"回答: {ans[:500]}")
    return result


run_case("新角色按需", "奥黛塔是什么角色？给我她的基本信息")
run_case("静态库命中", "胡桃是几星角色？")
run_case("知识问答", "推荐一个火系主C的配队")
