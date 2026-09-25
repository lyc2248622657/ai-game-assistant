"""记忆分层验证：偏好提取/读取 + 会话摘要生成 + 上下文注入（阶段三 P1）

用法：.venv\\Scripts\\python.exe scripts\\test_memory.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.prompts import build_agent_system_prompt, build_context_block, prepare_history
from app.memory.session_memory import SessionMemory
from app.memory.store import SessionStore
from app.memory.user_memory import UserMemory


def main() -> None:
    store = SessionStore()
    um = UserMemory()
    sm = SessionMemory(store)

    print("=== ① 用户偏好提取（按游戏隔离） ===")
    msgs = [
        {"role": "user", "content": "我喜欢胡桃，她好可爱"},
        {"role": "assistant", "content": "胡桃是5星火元素主C角色。"},
        {"role": "user", "content": "帮我看看火系蒸发队怎么配"},
        {"role": "assistant", "content": "胡桃蒸发队可配行秋、钟离。"},
    ]
    n = um.extract_and_store("genshin", msgs)
    prefs = um.get_prefs("genshin")
    print(f"提取/更新 {n} 条 → 当前偏好: {prefs}")
    assert prefs, "偏好提取失败"

    print("\n=== ② 会话摘要生成（消息≥12 条） ===")
    session = store.create_session("genshin", "记忆测试")
    for i in range(13):
        store.add_message(session["session_id"], "user" if i % 2 == 0 else "assistant",
                          f"第{i+1}轮：{'胡桃配队怎么组？' if i % 2 == 0 else '推荐行秋、钟离、夜兰，蒸发体系'}")
    summary = sm.refresh(session["session_id"], "genshin")
    print("摘要:", summary)
    assert summary, "摘要生成失败"

    print("\n=== ③ 上下文预算：摘要 + 最近 N 条 ===")
    hist = store.get_messages(session["session_id"])
    budget = prepare_history(hist, session_summary=summary, max_recent=8)
    print(f"原始 {len(hist)} 条 → 预算后 {len(budget)} 条（含 1 条摘要 + 最近 8 条）")
    assert len(budget) <= 9

    print("\n=== ④ 注入 system prompt ===")
    ctx = build_context_block(session_summary=summary, user_prefs=prefs)
    sys_prompt = build_agent_system_prompt("原神", ctx)
    assert "胡桃" in ctx and "配队" in summary
    assert ctx in sys_prompt
    print(sys_prompt[:400].replace("\n", " | "))
    print("\n记忆分层验证全部通过 ✓")


if __name__ == "__main__":
    main()
