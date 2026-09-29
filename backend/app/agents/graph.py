"""LangGraph 多智能体状态图：主管委派 → 子代理执行 → 动态重规划 → 汇总 → 自检 → 兜底

真实逻辑（阶段三）：
  - supervisor：LLM 意图识别 + 生成委派单（game_id / domain / delegate_to / brief）→ 委派给子代理
  - 子代理：genshin_agent / arknights_agent（实体与策略域：Function Calling 工具循环）/
            knowledge_agent（知识问答域：混合检索）
  - replan：Plan-Execute-Refine 动态重规划——执行后评估子任务完成度，未完成则补充计划再执行一轮
  - retrieve：混合检索（名称命中置顶 + RAG 向量召回重排 + 关键词兜底）
  - synthesize：LLM 依据工具/检索结果组织回答（只围绕命中实体）
  - reflect：Reflection 范式自检（忠实性/覆盖度/幻觉）→ 不合格回炉 synthesize 一次
  - memory：Memory RAG 向量召回历史记忆（用户偏好 + 会话摘要 + 常问实体）注入上下文
"""
import json
import re
from typing import Any, Literal

from langchain_core.messages import ToolMessage
from langgraph.graph import END, START, StateGraph

from app.agents.llm import get_chat_model
from app.agents.prompts import (
    REFLECT_INSTRUCTION,
    REPLAN_INSTRUCTION,
    SUPERVISOR_INSTRUCTION,
    SYNTHESIZE_RULES,
    build_agent_system_prompt,
    build_context_block,
    build_subagent_system_prompt,
    prepare_history,
)
from app.agents.state import AgentState
from app.core.logging import get_logger
from app.knowledge.games import registry
from app.memory.memory_rag import memory_rag
from app.memory.session_memory import session_memory
from app.memory.user_memory import user_memory
from app.tools.base import ToolContext
from app.tools.registry import tool_registry

logger = get_logger(__name__)

# 节点名常量
N_SUPERVISOR = "supervisor"
N_ROUTE = "route"
N_RETRIEVE = "retrieve"
N_TOOL = "tool"
N_REPLAN = "replan"
N_SYNTHESIZE = "synthesize"
N_REFLECT = "reflect"
N_FALLBACK = "fallback"

# 子代理委派对象 → 显示身份（1.1 修复：由游戏注册表动态派生，新增游戏无需改代码；
# knowledge_agent 为跨游戏通用子代理，固定保留）
def _delegate_identity() -> dict:
    ident = {"knowledge_agent": "通用知识子代理"}
    try:
        for g in registry.list_games():
            ident[g["agent_id"]] = g["agent_label"]
    except Exception:  # noqa: BLE001
        pass
    return ident


DELEGATE_IDENTITY = _delegate_identity()


def _emit(state: AgentState, event: dict) -> None:
    """向状态中的事件列表追加一条事件（后续由 API 层转为 SSE 转发）"""
    state.setdefault("events", []).append(event)


def _load_memory_context(state: AgentState) -> None:
    """加载记忆上下文（用户偏好 + 会话摘要 + Memory RAG 向量召回）注入 state.memory_context"""
    try:
        prefs = user_memory.get_prefs(state["game_id"])
        summary = None
        if state.get("session_id"):
            summary = session_memory.get_summary(state["session_id"])
        memory_hits = memory_rag.retrieve(state["game_id"], state.get("user_message", ""))
        ctx = build_context_block(session_summary=summary, user_prefs=prefs, memory_hits=memory_hits)
        state["memory_context"] = ctx
    except Exception as e:  # noqa: BLE001
        logger.warning("记忆加载失败: %s", e)
        state["memory_context"] = None


def _resolve_delegate(game_id: str, domain: str, delegate_to: str = "") -> str:
    """委派对象解析（1.1 修复）：由游戏注册表动态派生——entity/event 域委派给
    game_id 对应游戏的 agent_id；knowledge 域走通用子代理；显式 delegate_to 优先。
    新增游戏只需在 games.yaml 登记 agent_id，无需修改本函数。
    """
    if delegate_to in DELEGATE_IDENTITY:
        return delegate_to
    if domain in ("entity", "event") and game_id:
        try:
            game = registry.get_game(game_id, require_enabled=False)
            if game.agent_id in DELEGATE_IDENTITY:
                return game.agent_id
        except Exception:  # noqa: BLE001
            pass
    return "knowledge_agent"


# ---------- 主管智能体节点（多智能体协作） ----------
def supervisor_node(state: AgentState) -> AgentState:
    """主管智能体：理解用户问题 → 生成委派单（game_id/domain/delegate_to/brief）→ 委派给子代理。

    阶段三 P2：由 plan 升级为 supervisor；P2-2 解析失败自动重试一次；
    game_id 未判别时用关键词规则兜底归因。
    """
    logger.info("[%s] supervisor: %s", state["game_id"], state["user_message"][:50])
    _emit(state, {"type": "agent_start", "node_name": N_SUPERVISOR, "message": "主管智能体正在理解任务并规划委派…"})
    if not state.get("ablate", {}).get("memory"):
        _load_memory_context(state)
    data: dict = {}
    try:
        model = get_chat_model()
        for attempt in range(2):
            resp = model.invoke(
                [
                    {
                        "role": "system",
                        "content": build_agent_system_prompt(None, state.get("memory_context")) + "\n\n" + SUPERVISOR_INSTRUCTION,
                    },
                    {"role": "user", "content": state["user_message"]},
                ]
            )
            m = re.search(r"\{.*\}", resp.content or "", re.S)
            try:
                data = json.loads(m.group(0)) if m else {}
                break
            except Exception:  # noqa: BLE001
                data = {}
                if attempt == 0:
                    logger.warning("supervisor JSON 解析失败，重试一次")
                    _emit(state, {"type": "agent_start", "node_name": N_SUPERVISOR, "message": "意图识别失败，正在重试…"})
                    # 追加严格 JSON 约束后重试
                    strict_instruction = SUPERVISOR_INSTRUCTION + "\n【硬性要求】只输出一个合法 JSON 对象，不要任何解释或额外文本。"
                    resp = model.invoke(
                        [
                            {
                                "role": "system",
                                "content": build_agent_system_prompt(None, state.get("memory_context")) + "\n\n" + strict_instruction,
                            },
                            {"role": "user", "content": state["user_message"]},
                        ]
                    )
                    m = re.search(r"\{.*\}", resp.content or "", re.S)
                    try:
                        data = json.loads(m.group(0)) if m else {}
                    except Exception:  # noqa: BLE001
                        data = {}

        # ① 游戏判别：Agent 识别出的 game_id 覆盖初始默认值；未识别时关键词规则兜底
        detected_game = str(data.get("game_id") or "").strip().lower()
        if detected_game in ("genshin", "arknights"):
            state["game_id"] = detected_game
            _emit(state, {"type": "agent_start", "node_name": N_SUPERVISOR, "message": f"已识别游戏: {detected_game}"})
        else:
            msg = state["user_message"]
            if any(w in msg for w in ("方舟", "干员", "罗德岛", "源石", "博士", "明日方舟")):
                state["game_id"] = "arknights"
            elif any(w in msg for w in ("原神", "旅行者", "提瓦特", "派蒙", "璃月", "蒙德")):
                state["game_id"] = "genshin"
            _emit(state, {"type": "agent_start", "node_name": N_SUPERVISOR, "message": f"游戏归因兜底: {state['game_id']}"})

        is_entity = bool(data.get("is_entity_query"))
        etype = data.get("entity_type") or ""
        ename = data.get("entity_name") or ""
        valid_types = ("character", "weapon", "artifact", "food", "material", "level")
        domain = str(data.get("domain") or "").strip().lower()
        if domain not in ("entity", "knowledge", "event"):
            domain = "entity" if (is_entity and etype in valid_types) else "knowledge"
        state["task_type"] = "tool" if domain in ("entity", "event") else "knowledge"

        # ② 委派对象（Supervisor 决策）：domain + game_id 联合决定
        delegate_to = _resolve_delegate(state["game_id"], domain, str(data.get("delegate_to") or "").strip())
        state["delegate_to"] = delegate_to
        state["agent_identity"] = DELEGATE_IDENTITY.get(delegate_to, "子代理")
        brief = str(data.get("brief") or "").strip() or state["user_message"][:60]
        reason = str(data.get("reason") or "").strip() or f"属于{state['agent_identity']}领域"
        state["supervisor_decision"] = {
            "game_id": state["game_id"],
            "domain": domain,
            "delegate_to": delegate_to,
            "brief": brief,
            "reason": reason,
        }
        state["plan"] = f"委派: {state['agent_identity']} | 域: {domain} | {brief}"
        if domain == "entity":
            state["plan_entity"] = {"type": etype, "name": ename}
            state["guide_type"] = str(data.get("guide_type") or "").strip()

        # 任务分解：复合意图 → 子任务清单（前端展示 + 执行阶段引导 LLM 按规划自主调用工具）
        raw_subtasks = data.get("subtasks")
        if isinstance(raw_subtasks, list):
            subtasks = [
                {
                    "task": str(s.get("task") or "").strip() or f"子任务{i + 1}",
                    "description": str(s.get("description") or "").strip(),
                    "suggested_tool": str(s.get("suggested_tool") or "").strip(),
                    "target": str(s.get("target") or "").strip(),
                }
                for i, s in enumerate(raw_subtasks)
                if isinstance(s, dict)
            ]
            subtasks = [s for s in subtasks if s["task"] or s["description"]][:5]
        else:
            subtasks = []
        state["subtasks"] = subtasks
        if subtasks:
            _emit(state, {
                "type": "tasks", "node_name": N_SUPERVISOR,
                "tasks": subtasks,
                "message": f"已规划 {len(subtasks)} 个子任务",
            })
    except Exception as e:  # noqa: BLE001
        logger.warning("supervisor 失败，走知识问答: %s", e)
        state["task_type"] = "knowledge"
        state["delegate_to"] = "knowledge_agent"
        state["agent_identity"] = "通用知识子代理"
        state["plan"] = "意图识别失败，回退知识问答"
    _emit(state, {"type": "agent_end", "node_name": N_SUPERVISOR, "summary": state["plan"]})
    return state


def route_node(state: AgentState) -> AgentState:
    """路由节点：输出委派决策事件，按委派对象设置子代理身份，选择下游分支"""
    logger.info("[%s] route: delegate_to=%s task_type=%s", state["game_id"], state.get("delegate_to"), state.get("task_type"))
    _emit(state, {"type": "agent_start", "node_name": N_ROUTE, "message": "路由任务…"})
    dec = state.get("supervisor_decision") or {}
    identity = state.get("agent_identity") or "子代理"
    _emit(state, {
        "type": "subagent", "node_name": N_ROUTE,
        "delegate_to": state.get("delegate_to"),
        "identity": identity,
        "brief": dec.get("brief", ""),
        "message": f"主管委派 → {identity}",
    })
    _emit(state, {"type": "agent_end", "node_name": N_ROUTE, "summary": f"任务类型: {state['task_type']} · 执行: {identity}"})
    return state


# ---------- 检索节点 ----------
def retrieve_node(state: AgentState) -> AgentState:
    """RAG 检索：混合检索（名称命中置顶 + 向量召回 + 关键词兜底，与 ReAct 共用实现）"""
    logger.info("[%s] retrieve", state["game_id"])
    _emit(state, {"type": "agent_start", "node_name": N_RETRIEVE, "message": "检索知识库…", "agent": state.get("agent_identity")})
    try:
        game = registry.get_game(state["game_id"])
        if state.get("ablate", {}).get("hybrid"):
            # 消融：纯向量检索（去掉名称置顶/体系词/关键词兜底）
            from app.rag.retriever import retriever

            docs = retriever.retrieve(game, state["user_message"], top_k=4)
        else:
            from app.rag.retriever import hybrid_retrieve

            docs = hybrid_retrieve(game, state["user_message"], top_k=4)
        state["retrieved_docs"] = docs
        _emit(state, {"type": "agent_end", "node_name": N_RETRIEVE, "summary": f"检索到 {len(docs)} 条"})
        if docs:
            _emit(state, {
                "type": "retrieval", "node_name": N_RETRIEVE,
                "docs": [{"title": d["title"], "source": d.get("source", "")} for d in docs],
            })
    except Exception as e:  # noqa: BLE001
        logger.warning("retrieve 失败: %s", e)
        state["retrieved_docs"] = []
        _emit(state, {"type": "agent_end", "node_name": N_RETRIEVE, "summary": "检索失败（空）"})
    return state


# ---------- 工具节点（Function Calling 循环） ----------
def tool_node(state: AgentState) -> AgentState:
    """子代理工具执行：LLM 决策 → 工具执行 → 结果回填 → 再决策，最多循环 3 轮。

    动态重规划支持：第二轮执行时注入「补充计划」（replan_tasks），引导补做未完成子任务。
    """
    logger.info("[%s] tool", state["game_id"])
    _emit(state, {"type": "agent_start", "node_name": N_TOOL, "message": "调用工具…", "agent": state.get("agent_identity")})
    game = registry.get_game(state["game_id"])
    ctx = ToolContext(game)

    model = get_chat_model().bind_tools(tool_registry.schemas())
    delegate_to = state.get("delegate_to") or ("genshin_agent" if game.game_id == "genshin" else "arknights_agent")
    system = build_subagent_system_prompt(delegate_to, game.name, state.get("memory_context"))
    messages = [{"role": "system", "content": system}]
    messages.extend(prepare_history(state.get("messages", []), session_summary=None))
    user_msg = state["user_message"]
    # 关卡攻略场景：注入关卡名与攻略类型，引导 LLM 选择 search_stage_guides
    pe = state.get("plan_entity") or {}
    if pe.get("type") == "level" and pe.get("name"):
        gt = state.get("guide_type") or ""
        user_msg += (
            f"\n\n【任务提示】用户询问的是关卡「{pe.get('name')}」的攻略"
            + (f"，攻略类型为「{gt}」" if gt else "，未指定攻略类型")
            + "。请调用 search_stage_guides 工具，stage 传入关卡名"
            + (f"，guide_type 传入「{gt}」" if gt else "（guide_type 留空）")
            + "。"
        )
    messages.append({"role": "user", "content": user_msg})

    # 任务分解引导：把 plan 阶段识别的子任务清单注入（LLM 自主决策，规划仅作蓝图）
    task_plan = _build_task_plan_prompt(state.get("subtasks") or [])
    if task_plan:
        messages.append({"role": "user", "content": task_plan})

    # 动态重规划补充计划（第二轮执行）：上轮已完成结果 + 本轮需补做的子任务
    if state.get("replan_tasks"):
        messages.append({"role": "user", "content": _build_replan_prompt(state)})

    tool_results: list[dict] = []
    final_text = ""
    try:
        for _ in range(3):
            resp = model.invoke(messages)
            calls = getattr(resp, "tool_calls", None) or []
            if not calls:
                final_text = resp.content or ""
                break
            messages.append(resp)  # AIMessage（含 tool_calls）
            for tc in calls:
                name = tc.get("name", "")
                args = tc.get("args", {}) or {}
                # 关卡攻略：LLM 未传 guide_type 时由系统注入（保证攻略类型理解 100% 落地）
                if name == "search_stage_guides" and state.get("guide_type"):
                    if not args.get("guide_type"):
                        args["guide_type"] = state["guide_type"]
                logger.info("工具调用 %s args=%s", name, json.dumps(args, ensure_ascii=False)[:200])
                _emit(state, {
                    "type": "tool_call", "node_name": N_TOOL,
                    "tool_name": name, "arguments": args,
                    "message": f"调用工具 {name}", "agent": state.get("agent_identity"),
                })
                try:
                    result = tool_registry.execute(name, args, ctx)
                except Exception as e:  # noqa: BLE001
                    result = {"error": str(e)}
                _emit(state, {
                    "type": "tool_result", "node_name": N_TOOL,
                    "tool_name": name,
                    "result": json.dumps(result, ensure_ascii=False)[:400],
                    "message": f"{name} 执行完成", "agent": state.get("agent_identity"),
                })
                tool_results.append({"name": name, "args": args, "result": result})
                messages.append(
                    ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=tc.get("id", ""))
                )
        state["tool_results"] = tool_results
        state["final_answer"] = final_text or "（工具执行完成，未得到最终回答）"
        _emit(state, {"type": "agent_end", "node_name": N_TOOL, "summary": f"工具执行 {len(tool_results)} 次"})
    except Exception as e:  # noqa: BLE001
        logger.error("tool 节点异常: %s", e)
        state["error"] = str(e)
        state["final_answer"] = "抱歉，工具执行出错，请稍后再试。"
        _emit(state, {"type": "agent_end", "node_name": N_TOOL, "summary": "工具执行异常"})
    return state


def _build_replan_prompt(state: AgentState) -> str:
    """动态重规划补充计划提示：列出上轮已完成与本轮需补做的子任务"""
    done = [f"- {tr.get('name')}" for tr in state.get("tool_results", [])]
    lines = ["【动态重规划 · 补充执行】"]
    if done:
        lines.append("上一轮已执行工具：" + "、".join(done))
    lines.append("以下子任务尚未完成，请优先调用对应工具补做：")
    for i, s in enumerate(state.get("replan_tasks") or [], 1):
        tool = s.get("suggested_tool") or "（无对应工具）"
        target = f"，目标: {s['target']}" if s.get("target") else ""
        lines.append(f"{i}. {s.get('task')}: {s.get('description') or '—'}（建议工具: {tool}{target}）")
    return "\n".join(lines)


def _build_task_plan_prompt(subtasks: list[dict]) -> str:
    """把任务规划格式化为执行阶段引导提示（LLM 仍自主决策调用哪些工具）"""
    if not subtasks:
        return ""
    lines = ["【任务规划（已识别以下子任务，请按需自主调用对应工具；可一次同时调用多个工具）】"]
    for i, s in enumerate(subtasks, 1):
        tool = s.get("suggested_tool") or "（无对应工具）"
        target = f"，目标: {s['target']}" if s.get("target") else ""
        lines.append(f"{i}. {s.get('task')}: {s.get('description') or '—'}（建议工具: {tool}{target}）")
    return "\n".join(lines)


def _build_materials(state: AgentState) -> list[str]:
    """汇总检索/工具结果，作为 synthesize 与 reflect 共享的资料上下文"""
    materials: list[str] = []
    for d in state.get("retrieved_docs", []):
        materials.append(f"[资料] {d['title']}: {d['content']}")
    for tr in state.get("tool_results", []):
        res = tr.get("result", {})
        if isinstance(res, dict) and res.get("entity"):
            materials.append(f"[工具结果] {json.dumps(res['entity'], ensure_ascii=False)}")
        elif isinstance(res, dict):
            materials.append(f"[工具结果] {json.dumps(res, ensure_ascii=False)}")
        else:
            materials.append(f"[工具结果] {res}")
    return materials


def _find_related_entities(state: AgentState) -> list[str]:
    """P1-2：资料未收录时，查找同游戏库内相关实体（名称包含/被包含，排除精确命中）"""
    try:
        game = registry.get_game(state["game_id"])
        from app.tools.game_entity import FILE_BY_TYPE, load_entries

        q = state.get("user_message", "")
        related: list[str] = []
        seen: set[str] = set()
        for t in FILE_BY_TYPE:
            for e in load_entries(game.data_dir, t):
                n = str(e.get("name") or "").strip()
                if not n or n in seen:
                    continue
                if q and (q == n or q in n or n in q):
                    seen.add(n)
                    related.append(n)
        return related[:5]
    except Exception:  # noqa: BLE001
        return []


# ---------- 汇总节点 ----------
def synthesize_node(state: AgentState) -> AgentState:
    """LLM 依据检索/工具结果组织回答，生成引用（Reflection 回炉时带质检反馈）"""
    logger.info("[%s] synthesize", state["game_id"])
    _emit(state, {"type": "agent_start", "node_name": N_SYNTHESIZE, "message": "组织回答…"})

    materials = _build_materials(state)
    feedback = ""
    sr = state.get("self_reflect") or {}
    if sr.get("issues") and state.get("reflect_retries", 0) >= 1:
        feedback = "\n上一版回答经质检发现以下问题，请逐一修正后重新回答：\n- " + "\n- ".join(sr["issues"])

    try:
        if materials:
            model = get_chat_model()
            game = registry.get_game(state["game_id"])
            delegate_to = state.get("delegate_to") or ("genshin_agent" if game.game_id == "genshin" else "arknights_agent")
            system = build_subagent_system_prompt(delegate_to, game.name, state.get("memory_context")) + SYNTHESIZE_RULES
            resp = model.invoke(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"用户问题：{state['user_message']}\n\n资料：\n" + "\n".join(materials) + feedback},
                ]
            )
            state["final_answer"] = resp.content or "（未生成回答）"
        elif state.get("final_answer"):
            # 工具节点已直接产出回答（模型未调工具即回答的场景），保留不覆盖
            pass
        else:
            # P1-2：未收录 → 列出相关实体提示 + 引导补充资料（而非生硬"未找到"）
            related = _find_related_entities(state)
            state["related_entities"] = related
            if related:
                names = "、".join(related)
                state["final_answer"] = (
                    f"抱歉，知识库中暂未收录该内容的完整资料。以下相关内容可能对你有帮助：{names}。"
                    "若需要收录新实体，可点击「补充资料」提交，核实后即可入库。"
                )
            else:
                state["final_answer"] = "抱歉，知识库中暂未找到相关内容，换个问法试试？"
    except Exception as e:  # noqa: BLE001
        logger.error("synthesize 失败: %s", e)
        state["final_answer"] = "抱歉，回答生成失败，请稍后再试。"

    # 引用
    citations = []
    for d in state.get("retrieved_docs", []):
        citations.append({"doc_id": d["doc_id"], "title": d["title"], "content": d["content"][:600], "source": d.get("source", "")})
    for tr in state.get("tool_results", []):
        res = tr.get("result", {})
        if isinstance(res, dict) and res.get("entity"):
            e = res["entity"]
            citations.append({"doc_id": e.get("id", ""), "title": e.get("name", ""), "content": json.dumps(e, ensure_ascii=False)[:600], "source": e.get("source", "dynamic")})
            # 实体头像图片（工具已附带 image_url/本地 image 路径 → 统一取网络直链）
            img = e.get("image_url") or e.get("image") or ""
            if img and not state.get("entity_image"):
                state["entity_image"] = img
        # 攻略检索结果（search_guides / search_stage_guides）→ 前端渲染视频/链接卡片
        if isinstance(res, dict) and tr.get("name") in ("search_guides", "search_stage_guides") and res.get("found"):
            state["guides"] = {
                "videos": res.get("videos") or [],
                "search_url": res.get("search_url"),
                "wiki_url": res.get("wiki_url"),
                "api_ok": res.get("api_ok", False),
            }
    state["citations"] = citations

    # 猜测适配选项：按实体类型规则生成（不消耗 LLM token）
    suggestions = _build_suggestions(state)
    state["suggestions"] = suggestions
    if suggestions:
        _emit(state, {"type": "suggestions", "suggestions": suggestions, "message": "已生成推荐追问"})
    if state.get("entity_image"):
        _emit(state, {"type": "image", "image_url": state["entity_image"], "message": "已获取实体图片"})
    if state.get("related_entities"):
        _emit(state, {"type": "related_entities", "related_entities": state["related_entities"], "message": "已生成相关实体提示"})
    if state.get("guides"):
        _emit(state, {"type": "guides", "guides": state["guides"], "message": "已检索攻略资源"})
    _emit(state, {"type": "agent_end", "node_name": N_SYNTHESIZE, "summary": "回答生成完成"})
    return state


def _build_suggestions(state: AgentState) -> list[str]:
    """按识别实体生成"猜测适配选项"（规则生成，零 token 成本）。

    问角色 → 适配队伍 / 养成材料总需求统计 / 适配武器推荐 / 命之座效果；
    问武器 → 推荐角色 / 获取方式；料理 → 原型与获取；等等。
    """
    pe = state.get("plan_entity") or {}
    etype = pe.get("type", "")
    ename = str(pe.get("name") or "").strip()
    if not etype or not ename:
        return []
    # 关卡攻略场景（明日方舟 level）：生成攻略类型建议按钮（不依赖实体命中）
    if etype == "level":
        gt = state.get("guide_type") or ""
        base = [
            f"{ename}摆完挂机攻略",
            f"{ename}单核攻略",
            f"{ename}高配攻略",
            f"{ename}低配攻略",
        ]
        if gt:
            # 用户已指定类型，置顶对应选项
            return [f"{ename}{gt}攻略"] + [b for b in base if f"{ename}{gt}" not in b][:3]
        return base
    # 实体未命中时不生成建议（避免"查看XX适配队伍"这类无意义按钮）
    hit_found = False
    for tr in state.get("tool_results", []):
        res = tr.get("result", {})
        if isinstance(res, dict) and res.get("found") and res.get("entity"):
            hit_found = True
            ename = res["entity"].get("name") or ename
            break
    if not hit_found:
        return []
    # 按游戏区分话术：明日方舟用干员术语（潜能/精英化），原神用角色术语（命之座/养成）
    is_arknights = state.get("game_id") == "arknights"
    if is_arknights and etype == "character":
        return [
            f"查看{ename}适配队伍",
            f"查看{ename}精英化材料总需求统计",
            f"查看{ename}潜能提升效果",
            f"查看{ename}攻略视频",
        ]
    tpl = {
        "character": [
            "查看该角色适配队伍",
            "查看该角色养成材料总需求统计",
            "查看该角色适配武器推荐",
            "查看该角色命之座效果",
            "查看该角色攻略视频",
        ],
        "weapon": ["查看该武器推荐角色", "查看该武器获取方式"],
        "artifact": ["查看该圣遗物推荐角色", "查看该圣遗物获取方式"],
        "food": ["查看该料理获取方式", "查看该料理原型"],
        "material": ["查看该材料获取方式", "查看该材料用途"],
    }
    return [t.replace("该角色", ename).replace("该武器", ename).replace("该圣遗物", ename).replace("该料理", ename).replace("该材料", ename) for t in tpl.get(etype, [])]


def _replan_signals(state: AgentState) -> tuple[list[dict], bool]:
    """动态重规划规则预检（纯函数）：返回（待补做子任务, 是否有未收录/失败信号）"""
    executed_tools = {tr.get("name") for tr in state.get("tool_results", [])}
    pending = [
        s for s in state.get("subtasks", [])
        if s.get("suggested_tool") and s["suggested_tool"] not in executed_tools
    ]
    failed = False
    for tr in state.get("tool_results", []):
        res = tr.get("result", {})
        if isinstance(res, dict) and (res.get("found") is False or res.get("error")):
            failed = True
        if isinstance(res, dict) and res.get("found") is False:
            failed = True
    return pending, failed


# ---------- 动态重规划节点（Plan-Execute-Refine） ----------
def replan_node(state: AgentState) -> AgentState:
    """执行后评估：子任务是否有未完成项 → 生成补充计划 → 二次执行（最多一轮）

    触发信号（规则预检）：子任务建议的工具未被调用，或工具结果出现未收录/空/错误；
    预检命中且重规划未超限 → LLM 评估剩余任务 → 追加 replan_tasks。
    """
    state["replan_needed"] = False
    if state.get("ablate", {}).get("replan"):
        # 消融：禁用动态重规划
        logger.info("[%s] replan 已消融（跳过）", state["game_id"])
        return state
    if state.get("replan_count", 0) >= 1 or not state.get("subtasks"):
        return state
    pending, failed = _replan_signals(state)
    if not pending and not failed:
        return state

    logger.info("[%s] replan 预检命中: pending=%d failed=%s", state["game_id"], len(pending), failed)
    _emit(state, {"type": "agent_start", "node_name": N_REPLAN, "message": "评估子任务完成度，动态调整计划…"})
    try:
        model = get_chat_model()
        transcript = (
            f"用户问题：{state['user_message']}\n\n"
            f"规划子任务：{json.dumps(state.get('subtasks', []), ensure_ascii=False)}\n\n"
            f"已执行工具：{json.dumps([{'name': t.get('name'), 'result': t.get('result', {})} for t in state.get('tool_results', [])], ensure_ascii=False)}"
        )
        resp = model.invoke(
            [
                {"role": "system", "content": REPLAN_INSTRUCTION},
                {"role": "user", "content": transcript},
            ]
        )
        m = re.search(r"\{.*\}", resp.content or "", re.S)
        data = json.loads(m.group(0)) if m else {}
        if not data.get("complete"):
            remaining = [
                {
                    "task": str(s.get("task") or "").strip() or f"补充任务{i + 1}",
                    "description": str(s.get("description") or "").strip(),
                    "suggested_tool": str(s.get("suggested_tool") or "").strip(),
                    "target": str(s.get("target") or "").strip(),
                }
                for i, s in enumerate(data.get("remaining") or [])
                if isinstance(s, dict) and (s.get("task") or s.get("description"))
            ][:4]
            if remaining:
                state["replan_tasks"] = remaining
                state["replan_count"] = state.get("replan_count", 0) + 1
                state["replan_needed"] = True
                _emit(state, {
                    "type": "replan", "node_name": N_REPLAN,
                    "remaining": remaining,
                    "message": f"动态调整计划：补充 {len(remaining)} 个子任务后再次执行",
                })
                _emit(state, {"type": "agent_end", "node_name": N_REPLAN, "summary": f"重规划完成，补做 {len(remaining)} 项"})
                return state
        _emit(state, {"type": "agent_end", "node_name": N_REPLAN, "summary": "评估完成，无需补充"})
    except Exception as e:  # noqa: BLE001
        logger.warning("replan 失败，跳过: %s", e)
        _emit(state, {"type": "agent_end", "node_name": N_REPLAN, "summary": "重规划异常，跳过"})
    return state


# ---------- Reflection 自检节点 ----------
def reflect_node(state: AgentState) -> AgentState:
    """Reflection 范式：质检回答 → 不通过则回炉 synthesize 一次（最多一次）"""
    logger.info("[%s] reflect", state["game_id"])
    _emit(state, {"type": "agent_start", "node_name": N_REFLECT, "message": "质检回答…"})
    if state.get("ablate", {}).get("reflect"):
        # 消融：禁用 Reflection 自检（直接通过，不回炉）
        state["self_reflect"] = {"passed": True, "issues": [], "revised": ""}
        _emit(state, {"type": "agent_end", "node_name": N_REFLECT, "summary": "质检已消融（直接通过）"})
        return state
    answer = state.get("final_answer") or ""
    materials = _build_materials(state)
    try:
        model = get_chat_model()
        resp = model.invoke(
            [
                {"role": "system", "content": REFLECT_INSTRUCTION},
                {
                    "role": "user",
                    "content": f"用户问题：{state['user_message']}\n\n资料：\n" + "\n".join(materials)
                    + f"\n\n现有回答：\n{answer}",
                },
            ]
        )
        import re

        m = re.search(r"\{.*\}", resp.content or "", re.S)
        data = json.loads(m.group(0)) if m else {}
        passed = str(data.get("pass", "")).lower() in ("true", "1", "yes")
        issues = [str(i) for i in data.get("issues", []) if i] or ([] if passed else ["未通过质检"])
        revised = str(data.get("revised_answer") or "").strip()
        state["self_reflect"] = {"passed": passed, "issues": issues[:5], "revised": revised}

        if passed:
            _emit(state, {"type": "agent_end", "node_name": N_REFLECT, "summary": "质检通过 ✓"})
        else:
            state["reflect_retries"] = state.get("reflect_retries", 0) + 1
            if revised:
                # 质检器直接给出修正版，覆盖回答（不再回炉）
                state["final_answer"] = revised
                state["self_reflect"]["revised_used"] = True
                _emit(state, {
                    "type": "agent_end", "node_name": N_REFLECT,
                    "summary": f"质检发现 {len(issues)} 处问题，已修正回答",
                })
            else:
                _emit(state, {
                    "type": "agent_end", "node_name": N_REFLECT,
                    "summary": f"质检发现 {len(issues)} 处问题，重新组织回答",
                })
    except Exception as e:  # noqa: BLE001
        logger.warning("reflect 失败，跳过质检: %s", e)
        state["self_reflect"] = {"passed": True, "issues": [], "revised": ""}
        _emit(state, {"type": "agent_end", "node_name": N_REFLECT, "summary": "质检异常，跳过"})
    return state


def fallback_node(state: AgentState) -> AgentState:
    """兜底节点：所有异常路径的统一收敛点"""
    logger.warning("[%s] fallback: error=%s", state["game_id"], state.get("error"))
    _emit(state, {"type": "agent_start", "node_name": N_FALLBACK, "message": "处理异常…"})
    state["final_answer"] = "抱歉，我暂时无法完成这个请求，请换个说法试试。"
    _emit(state, {"type": "agent_end", "node_name": N_FALLBACK, "summary": "已降级回复"})
    return state


# ---------- 条件路由 ----------
def decide_next(state: AgentState) -> Literal["retrieve", "tool", "synthesize"]:
    """根据委派域决定下游分支：实体/策略域 → tool；知识问答域 → retrieve"""
    t = state.get("task_type", "knowledge")
    if t == "tool":
        return N_TOOL
    return N_RETRIEVE


def decide_replan(state: AgentState) -> Literal["tool", "synthesize"]:
    """重规划判断：需要补充执行 → 回 tool 二次执行；否则进入汇总"""
    if state.get("replan_needed"):
        return N_TOOL
    return N_SYNTHESIZE


def decide_reflect(state: AgentState) -> Literal["synthesize", "end"]:
    """质检未通过且未给出修正版 → 回炉 synthesize 一次；否则结束"""
    sr = state.get("self_reflect") or {}
    if (not sr.get("passed")) and (not sr.get("revised_used")) and state.get("reflect_retries", 0) < 1:
        return N_SYNTHESIZE
    return "end"


def decide_after_retrieve(state: AgentState) -> Literal["synthesize", "tool"]:
    """P0-2 降级链闭环：检索为空 → 自动转工具节点重试（Agent 自主尝试，
    而非直接输出"未收录"）；LLM 在工具节点自行决策是否调用实体工具。"""
    if not state.get("retrieved_docs") and not state.get("final_answer"):
        state["task_type"] = "tool"
        logger.info("检索为空，自动转工具重试（降级链闭环）")
        _emit(state, {"type": "agent_start", "node_name": N_RETRIEVE, "message": "检索未命中，自动转工具重试…"})
        return N_TOOL
    return N_SYNTHESIZE


def build_graph():
    """构建并编译状态图：
    supervisor（委派）→ 子代理执行（retrieve/tool）→ replan（动态重规划）→ synthesize → reflect → 回炉/结束
    """
    g = StateGraph(AgentState)

    g.add_node(N_SUPERVISOR, supervisor_node)
    g.add_node(N_ROUTE, route_node)
    g.add_node(N_RETRIEVE, retrieve_node)
    g.add_node(N_TOOL, tool_node)
    g.add_node(N_REPLAN, replan_node)
    g.add_node(N_SYNTHESIZE, synthesize_node)
    g.add_node(N_REFLECT, reflect_node)
    g.add_node(N_FALLBACK, fallback_node)

    g.add_edge(START, N_SUPERVISOR)
    g.add_edge(N_SUPERVISOR, N_ROUTE)
    g.add_conditional_edges(N_ROUTE, decide_next, {N_RETRIEVE: N_RETRIEVE, N_TOOL: N_TOOL, N_SYNTHESIZE: N_SYNTHESIZE})
    g.add_conditional_edges(N_RETRIEVE, decide_after_retrieve, {N_SYNTHESIZE: N_SYNTHESIZE, N_TOOL: N_TOOL})
    g.add_edge(N_TOOL, N_REPLAN)
    g.add_conditional_edges(N_REPLAN, decide_replan, {N_TOOL: N_TOOL, N_SYNTHESIZE: N_SYNTHESIZE})
    g.add_edge(N_SYNTHESIZE, N_REFLECT)
    g.add_conditional_edges(N_REFLECT, decide_reflect, {N_SYNTHESIZE: N_SYNTHESIZE, "end": END})
    g.add_edge(N_FALLBACK, END)
    return g.compile()


app_graph = build_graph()
