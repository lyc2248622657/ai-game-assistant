"""A2A 多智能体协同演示 CLI：一个复合请求 → 分解 → 派发 → 汇总

用法（backend 目录下，用项目 venv）：
  .venv\\Scripts\\python.exe scripts\\a2a_demo.py
  .venv\\Scripts\\python.exe scripts\\a2a_demo.py --no-llm   # 全链路离线（关键词分解+结构化汇总）
"""
import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents import a2a  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="A2A 多智能体协同演示")
    parser.add_argument("--no-llm", action="store_true", help="禁用 LLM（关键词分解 + 结构化汇总）")
    args = parser.parse_args()

    tasks = [
        "帮我查一下明日方舟能天使的强度，顺便问一下员工病假超过几天需要开诊断证明",
        "统计一下文档库和方舟知识库分别有多少块，再查原神胡桃是几星角色",
    ]
    for task in tasks:
        print("=" * 70)
        print("请求:", task)
        out = a2a.run(task, use_llm=not args.no_llm)
        print("分解子任务:", [f"{r['agent']}({r['task']})" for r in out["subtasks"]])
        print("汇总回答:")
        print(out["answer"])


if __name__ == "__main__":
    main()
