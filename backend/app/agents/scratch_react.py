"""自研轻量 ReAct 循环模块（阶段三 P1）

不依赖 LangGraph，手写经典 ReAct 循环：Thought → Action → Observation → ... → Final。
复用项目统一的工具注册表与 RAG 检索器，展示对 Agent 循环原理的底层理解。

输出结构：
  - answer: 最终回答
  - trace: 每一步的 (thought, action, observation)
  - usage: token 消耗统计（prompt/completion/total）
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from app.agents.llm import get_chat_model
from app.core.logging import get_logger
from app.knowledge.games import registry
from app.tools.base import ToolContext
from app.tools.registry import tool_registry

logger = get_logger(__name__)

MAX_STEPS = 4

REACT_SYSTEM = """你是多游戏智能助手，可回答《原神》《明日方舟》的游戏问题。采用 ReAct 循环作答。你有两个工具：
- query_game_entity：查询指定游戏实体（角色/干员/武器/圣遗物/料理/材料）的自身属性，参数 {game: genshin|arknights, type: character|weapon|artifact|food|material, name: 实体名}
- search_knowledge：在知识库中检索与问题相关的资料，参数 {query: 检索词}

规则：
1. 先判断问题属于哪个游戏：原神角色/武器（胡桃、天空之翼…）→ genshin；明日方舟干员（银灰、能天使…）→ arknights。
2. 需要具体实体属性时调用 query_game_entity（必须传对 game）；需要配队/推荐/对比等背景资料时调用 search_knowledge。
3. 只使用工具返回的资料回答，资料中没有的明确说『资料未收录』，不得编造。
4. 得到足够资料后直接给出最终回答。

每步只输出一个 JSON：
{"thought": "你的思考", "action": {"tool": "工具名", "args": {...}} 或 null, "final": "最终回答（action 为 null 时填写，否则为空字符串）"}"""


def _parse_decision(text: str) -> dict:
    """鲁棒解析 ReAct 决策：兼容 JSON 输出与经典 ReAct 文本格式
    （thought: ... / action: ... / action input: ... / final answer: ...）"""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S).strip()

    # ① JSON 格式
    try:
        return json.loads(t)
    except Exception:  # noqa: BLE001
        for pat in (r"\{.*?\}", r"\{.*\}"):
            m = re.search(pat, t, re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:  # noqa: BLE001
                    continue

    # ② 经典 ReAct 文本格式
    def _grab(pattern: str) -> str:
        m = re.search(pattern, t, re.I | re.S)
        return m.group(1).strip() if m else ""

    thought = _grab(r"(?:thought|思考)\s*[:：]\s*(.+)")
    final = _grab(r"(?:final\s*answer|final)\s*[:：]\s*(.+)")
    tool = _grab(r"(?:action|tool)\s*[:：]\s*([\w_]+)")
    action_input = _grab(r"(?:action\s*input)\s*[:：]\s*(.+)")
    # final 优先（无论 action 是否为 null，只要给出最终回答就直接返回）
    if final:
        return {"thought": thought[:200], "action": None, "final": final}
    # action 非空且非 null/none 才是真正的工具调用
    if tool and tool.lower() not in ("null", "none", "无"):
        args: dict = {}
        if action_input:
            try:
                args = json.loads(action_input)
            except Exception:  # noqa: BLE001
                parts = [p.strip() for p in action_input.split(",") if p.strip()]
                if tool == "query_game_entity" and len(parts) >= 2:
                    args = {"type": parts[0], "name": parts[1]}
                else:
                    args = {"query": action_input}
        return {"thought": thought[:200], "action": {"tool": tool, "args": args}, "final": ""}
    return {}


class ScratchReAct:
    """手写 ReAct 循环：Think → Act → Observe → Final"""

    def __init__(self, max_steps: int = MAX_STEPS):
        self.max_steps = max_steps
        self._retried = False

    def _observe(self, tool: str, args: dict, ctx: ToolContext) -> dict:
        """执行动作并返回观察结果（控制长度保证观察消息 JSON 完整）"""
        if tool == "search_knowledge":
            from app.rag.retriever import hybrid_retrieve

            docs = hybrid_retrieve(ctx.game, args.get("query", ""), top_k=3)
            # 记录引用来源（供最终回答核验与 Judge 评估）
            for d in docs:
                self._citations.append({"doc_id": d["doc_id"], "title": d["title"], "content": d["content"][:400], "source": d.get("source", "static")})
            return {"docs": [{"title": d["title"], "content": d["content"][:280]} for d in docs]}
        if tool == "query_game_entity":
            result = tool_registry.execute("query_game_entity", args, ctx)
            entity = (result or {}).get("entity") if isinstance(result, dict) else None
            if entity:
                self._citations.append({
                    "doc_id": entity.get("id", ""),
                    "title": entity.get("name", ""),
                    "content": json.dumps(entity, ensure_ascii=False)[:600],
                    "source": entity.get("source", "dynamic"),
                })
            return result
        return {"error": f"未知工具: {tool}"}

    def run(self, game_id: str, user_message: str, messages: list[dict] | None = None) -> dict:
        start = time.perf_counter()
        self._retried = False
        self._citations: list[dict] = []
        ctx = ToolContext(registry.get_game(game_id))
        model = get_chat_model()
        trace: list[dict] = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in (messages or [])[-4:]
            if m.get("role") in ("user", "assistant")
        ]

        msgs = [{"role": "system", "content": REACT_SYSTEM}]
        msgs.extend(history)
        msgs.append({"role": "user", "content": user_message})

        for step in range(1, self.max_steps + 1):
            resp = model.invoke(msgs)
            # token 统计
            um = getattr(resp, "usage_metadata", None) or {}
            usage["prompt_tokens"] += um.get("input_tokens", 0)
            usage["completion_tokens"] += um.get("output_tokens", 0)
            usage["total_tokens"] += um.get("total_tokens", 0)

            decision = _parse_decision(resp.content)
            if not decision or (not decision.get("action") and not decision.get("final")):
                # 输出格式异常（非 JSON 也非标准 ReAct 文本）→ 追加修正指令重试一次
                if not self._retried:
                    self._retried = True
                    msgs.append({
                        "role": "user",
                        "content": '格式错误。请只输出一个 JSON（不要其他任何文字）：'
                                   '{"thought": "简短思考", "action": null, "final": "你的最终回答"}',
                    })
                    continue
                decision = {"thought": "", "action": None, "final": (resp.content or "").strip()}
            # 兜底：模型直接给回答文本 → 原文作为最终回答
            if not decision and (resp.content or "").strip():
                decision = {"thought": "", "action": None, "final": resp.content.strip()}
            thought = str(decision.get("thought", ""))[:200]
            action = decision.get("action")
            final = str(decision.get("final") or "").strip()

            if not action or final:
                trace.append({
                    "step": step, "thought": thought, "action": None, "final": final,
                    "raw": (resp.content or "")[:300],
                })
                return {
                    "answer": final or "（未生成回答）",
                    "citations": self._citations,
                    "trace": trace,
                    "usage": usage,
                    "wall_time_s": round(time.perf_counter() - start, 2),
                    "steps": step,
                }

            tool = action.get("tool", "")
            args = action.get("args", {}) or {}
            observation = self._observe(tool, args, ctx)
            trace.append({"step": step, "thought": thought, "action": action, "observation": json.dumps(observation, ensure_ascii=False)[:400]})
            msgs.append({"role": "assistant", "content": f"thought: {thought}\naction: {json.dumps(action, ensure_ascii=False)}"})
            msgs.append({"role": "user", "content": f"observation: {json.dumps(observation, ensure_ascii=False)[:2500]}"})

        return {"answer": "（达到最大步数，未得到最终回答）", "citations": self._citations, "trace": trace, "usage": usage,
                "wall_time_s": round(time.perf_counter() - start, 2), "steps": self.max_steps}


scratch_react = ScratchReAct()
