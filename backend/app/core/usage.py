"""LLM 用量统计：通过 LangChain 回调自动累计所有模型调用的 token（阶段三 P1）

设计：
  - UsageStats 为进程级单例，挂在 get_chat_model() 的 callbacks 上；
  - 所有通过该模型的调用（Agent 图 / ReAct / Judge / 记忆提取）自动计入；
  - eval_runner 跑前 reset()、跑后 snapshot() → 精确的本轮评测 token；
  - chat 接口用「请求前/后 snapshot 差值」得到单轮对话消耗。
"""
from __future__ import annotations

import threading

from langchain_core.callbacks import BaseCallbackHandler


class _UsageHandler(BaseCallbackHandler):
    """on_llm_end 时累计 token（兼容 langchain 新旧字段命名）"""

    def __init__(self, stats: "UsageStats"):
        self._stats = stats

    def on_llm_end(self, response, **kwargs):  # noqa: ANN001
        try:
            llm_output = response.llm_output or {}
            usage = llm_output.get("token_usage") or {}
            self._stats.add(
                input_tokens=usage.get("input_tokens") or usage.get("prompt_tokens") or 0,
                output_tokens=usage.get("output_tokens") or usage.get("completion_tokens") or 0,
            )
        except Exception:  # noqa: BLE001
            pass  # 统计失败不影响业务


class UsageStats:
    """进程级 token 累计器（线程安全）"""

    def __init__(self):
        self._lock = threading.Lock()
        self._input = 0
        self._output = 0
        self._calls = 0
        self._handler: _UsageHandler | None = None

    @property
    def handler(self) -> _UsageHandler:
        if self._handler is None:
            self._handler = _UsageHandler(self)
        return self._handler

    def add(self, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self._input += int(input_tokens or 0)
            self._output += int(output_tokens or 0)
            self._calls += 1

    def reset(self) -> None:
        with self._lock:
            self._input = 0
            self._output = 0
            self._calls = 0

    def snapshot(self) -> dict:
        """当前累计快照（input/output/total/calls）"""
        with self._lock:
            return {
                "input_tokens": self._input,
                "output_tokens": self._output,
                "total_tokens": self._input + self._output,
                "llm_calls": self._calls,
            }


# 进程级单例（模块加载即创建）
usage_stats = UsageStats()
