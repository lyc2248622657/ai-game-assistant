"""Agent 图状态定义"""
from typing import Any, Optional, TypedDict


class AgentState(TypedDict, total=False):
    """贯穿 LangGraph 全流程的共享状态。

    设计原则：每个节点只读写自己负责的字段，职责单一、便于调试。
    """

    # 会话与上下文
    game_id: str                    # 当前游戏标识（驱动检索与工具按游戏路由）
    session_id: Optional[str]
    user_message: str               # 本轮用户输入
    messages: list[dict]            # 历史消息（记忆注入用）

    # 规划与路由
    plan: Optional[str]             # 任务分解结果
    task_type: Optional[str]        # knowledge / tool / combined / fallback
    plan_entity: Optional[dict]     # 实体查询意图（type/name）
    guide_type: Optional[str]       # 关卡攻略类型（摆完挂机/单核/高配/低配/肉鸽N15）
    subtasks: list[dict]            # 任务分解：复合意图拆分的子任务清单 [{task, description, suggested_tool, target}]

    # 多智能体协作（Supervisor 委派）
    supervisor_decision: Optional[dict]  # 委派单 {game_id, domain, delegate_to, brief, reason}
    agent_identity: Optional[str]        # 当前执行子代理身份（如 原神子代理 / 明日方舟子代理 / 通用知识子代理）
    delegate_to: Optional[str]           # genshin_agent / arknights_agent / knowledge_agent

    # 动态重规划（Plan-Execute-Refine）
    replan_count: int               # 重规划次数（上限 1）
    replan_tasks: list[dict]        # 重规划后补充的子任务
    replan_needed: bool             # 是否触发重规划评估

    # 执行结果
    retrieved_docs: list[dict]      # RAG 检索结果（含引用信息）
    tool_results: list[dict]        # 工具执行结果
    citations: list[dict]           # 最终引用列表

    # 可靠性
    error: Optional[str]            # 异常信息
    retry_count: int                # 重试计数

    # Reflection 自检（阶段三：synthesize 后质检 → 不合格回炉一次）
    reflect_retries: int            # 质检回炉次数（上限 1）
    self_reflect: Optional[dict]    # 质检结果 {passed, issues, revised}

    # 输出
    final_answer: Optional[str]     # 汇总后的最终回答
    suggestions: list[str]          # 猜测适配选项（问实体时生成，前端渲染为可点击按钮）
    entity_image: Optional[str]     # 实体头像图片 URL（角色图/武器图，前端渲染）
    events: list[dict]              # Agent 过程事件（SSE 转发给前端时间线）


def initial_state(
    game_id: str,
    session_id: str | None,
    user_message: str,
    messages: list[dict],
) -> AgentState:
    return {
        "game_id": game_id,
        "session_id": session_id,
        "user_message": user_message,
        "messages": messages,
        "task_type": None,
        "plan": None,
        "guide_type": None,
        "subtasks": [],
        "supervisor_decision": None,
        "agent_identity": None,
        "delegate_to": None,
        "replan_count": 0,
        "replan_tasks": [],
        "replan_needed": False,
        "retrieved_docs": [],
        "tool_results": [],
        "citations": [],
        "error": None,
        "retry_count": 0,
        "reflect_retries": 0,
        "self_reflect": None,
        "final_answer": None,
        "suggestions": [],
        "entity_image": None,
        "events": [],
    }
