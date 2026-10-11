"""A2A 多智能体协同（Agent-to-Agent 演示）

对齐岗位 22（深圳德恩，南方电网项目点名 RAG+MCP+A2A）与「企业级智能体平台实操成标配」信号：
外部一个请求 → 协调者（orchestrator）做任务分解 → 派发独立智能体执行（游戏域 / 企业文档域 /
向量运维域）→ 汇总带来源回答。与 LangGraph 图内编排互补：这里展示的是「协议级」多智能体协同，
即多个独立智能体通过协调者协作解决复合任务，且整体暴露为单个 MCP 工具（A2A over MCP）。

链路：run(task)
  decompose：LLM 按智能体清单分解为子任务（无 LLM 时关键词规则兜底）
  dispatch ：逐个智能体执行（每个智能体内部自带工具链）
  synthesize：LLM 汇总各智能体结果（无 LLM 时结构化拼接）
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from app.core.logging import get_logger
from app.knowledge.games import registry
from app.rag import document_qa, vector_admin
from app.rag.retriever import hybrid_retrieve
from app.tools.base import ToolContext
from app.tools.game_entity import QueryGameEntityTool

logger = get_logger(__name__)

# ---------- 子智能体注册表（capabilities 供 LLM 分解参考） ----------


@dataclass
class SubAgent:
    """一个独立智能体：capabilities 描述 + 执行函数"""
    name: str
    capabilities: str
    run: Callable[[dict], dict]


def _run_game_agent(args: dict) -> dict:
    """游戏域智能体：实体查询（静态→动态→LLM 生成）+ 混合检索"""
    game_id = str(args.get("game") or "").strip().lower()
    if game_id not in ("genshin", "arknights"):
        return {"ok": False, "message": "未知游戏，支持 genshin / arknights"}
    game = registry.get_game(game_id)
    ctx = ToolContext(game)
    entity_args = {"type": str(args.get("type") or "character"), "name": str(args.get("name") or "")}
    out: dict[str, Any] = {"ok": True}
    if entity_args["name"]:
        out["entity"] = QueryGameEntityTool().run(entity_args, ctx)
    query = str(args.get("query") or "")
    if query:
        out["retrieval"] = hybrid_retrieve(game, query, top_k=4)
    if not entity_args["name"] and not query:
        return {"ok": False, "message": "需要 name 或 query"}
    return out


def _run_doc_agent(args: dict) -> dict:
    """企业文档域智能体：文档问答（带引用）/ 文档清单"""
    question = str(args.get("question") or "").strip()
    if not question:
        return {"ok": False, "message": "需要 question"}
    return {"ok": True, **document_qa.ask(question, top_k=int(args.get("top_k") or 4))}


def _run_vector_agent(args: dict) -> dict:
    """向量运维域智能体：集合统计 / 全部集合概况"""
    if args.get("action") == "list":
        return {"ok": True, "collections": vector_admin.list_collections()}
    collection = str(args.get("collection") or "documents")
    return {"ok": True, "stats": vector_admin.collection_stats(collection)}


SUB_AGENTS: list[SubAgent] = [
    SubAgent(
        "game_agent",
        "游戏域：查询原神/明日方舟实体（角色、干员、武器、圣遗物、材料）或知识检索。args: {game, type, name, query}",
        _run_game_agent,
    ),
    SubAgent(
        "doc_agent",
        "企业文档域：基于已导入的客户文档回答问题（带引用）。args: {question, top_k}",
        _run_doc_agent,
    ),
    SubAgent(
        "vector_agent",
        "向量库运维域：统计集合（总量/按文档/孤儿块）或列出全部集合。args: {collection, action}",
        _run_vector_agent,
    ),
]
AGENT_INDEX = {a.name: a for a in SUB_AGENTS}


# ---------- 任务分解（LLM 主路径 + 关键词兜底） ----------

_DECOMPOSE_INSTRUCTION = """你是多智能体协调者。把用户的请求分解为子任务，分配给可用的智能体。
可用智能体：
{capabilities}
输出规则：只输出一个 JSON 数组，每项 {"agent": 智能体名, "task": 子任务说明, "args": {参数}}；
一个子任务只能分给一个智能体；与游戏无关的文档问题分给 doc_agent；统计/清理类分给 vector_agent。"""


def _keyword_decompose(task: str) -> list[dict]:
    """无 LLM 时的关键词规则兜底（保证演示可离线跑通）"""
    runs: list[dict] = []
    vector_words = ("统计", "集合", "孤儿", "清理", "块数", "多少条", "多少块", "概况")
    doc_content_words = ("病假", "制度", "手册", "请假", "报销", "培训", "员工", "入职", "离职", "远程办公")
    doc_ask_words = ("需要", "证明", "几天", "规定", "条款", "流程", "如何", "什么")
    if any(w in task for w in vector_words):
        runs.append({"agent": "vector_agent", "task": "向量库统计", "args": {}})
    elif any(w in task for w in doc_content_words) or any(w in task for w in doc_ask_words):
        runs.append({"agent": "doc_agent", "task": "企业文档问答", "args": {"question": task}})
    if any(w in task for w in ("原神", "方舟", "干员", "角色", "武器", "圣遗物", "能天使", "胡桃", "雷神", "钟离", "烟绯", "强度", "配队")):
        # 离线兜底走知识检索（query=原始任务即可命中实体条目），实体查询留给 LLM 分解
        runs.append({
            "agent": "game_agent", "task": "游戏知识查询",
            "args": {"game": "arknights" if ("方舟" in task or "干员" in task) else "genshin", "query": task},
        })
    return runs


def decompose(task: str, use_llm: bool = True) -> list[dict]:
    """把用户请求分解为子任务清单（LLM 主路径，失败/禁用时关键词规则兜底）"""
    if use_llm:
        try:
            from app.agents.llm import get_chat_model

            caps = "\n".join(f"- {a.name}: {a.capabilities}" for a in SUB_AGENTS)
            resp = get_chat_model().invoke(
                [
                    {"role": "system", "content": _DECOMPOSE_INSTRUCTION.format(capabilities=caps)},
                    {"role": "user", "content": task},
                ]
            )
            text = re.sub(r"```(?:json)?", "", resp.content or "").strip()  # 剥 markdown 围栏
            m = re.search(r"\[.*\]", text, re.S)
            runs = json.loads(m.group(0)) if m else []
            valid = [
                {"agent": str(r.get("agent")), "task": str(r.get("task") or "子任务"), "args": r.get("args") or {}}
                for r in runs if isinstance(r, dict) and r.get("agent") in AGENT_INDEX
            ]
            if valid:
                logger.info("[a2a] LLM 分解 %d 个子任务", len(valid))
                return valid
        except Exception as e:  # noqa: BLE001
            logger.warning("[a2a] LLM 分解失败，走关键词兜底: %s", e)
    runs = _keyword_decompose(task)
    logger.info("[a2a] 关键词兜底分解 %d 个子任务", len(runs))
    return runs


# ---------- 派发执行 ----------


def dispatch(runs: list[dict]) -> list[dict]:
    """逐智能体执行：每个子任务独立运行，单点失败不阻断整体（降级标记 error）"""
    results: list[dict] = []
    for i, run in enumerate(runs, 1):
        agent_name = str(run.get("agent") or "unknown")
        agent = AGENT_INDEX.get(agent_name)
        try:
            if agent is None:
                payload = {"ok": False, "message": f"未知智能体: {agent_name}"}
            else:
                payload = agent.run(run.get("args") or {})
            results.append({"index": i, "agent": agent_name, "task": run.get("task", ""), "result": payload})
            logger.info("[a2a] #%d %s 完成", i, agent_name)
        except Exception as e:  # noqa: BLE001
            logger.warning("[a2a] #%d %s 执行异常: %s", i, agent_name, e)
            results.append({"index": i, "agent": agent_name, "task": run.get("task", ""), "result": {"ok": False, "message": str(e)}})
    return results


# ---------- 汇总（LLM 主路径 + 结构化兜底） ----------

_SYNTHESIZE_INSTRUCTION = """你是多智能体协调者。以下是各子智能体的执行结果，请面向用户组织成一份连贯、简洁的回答。
每个结论标注来源智能体名（如 [game_agent]），未成功执行的子任务如实说明。不要编造结果里没有的信息。"""


def _summarize_result(result: dict) -> str:
    """把单个智能体结果压成可读摘要（供 LLM 与结构化兜底共用）"""
    if not result.get("ok"):
        return f"执行失败: {result.get('message', '')}"
    # 实体查询结果
    entity = result.get("entity") or {}
    if entity and entity.get("found"):
        e = entity.get("entity") or {}
        parts = [f"{e.get('name')}（{e.get('role') or e.get('element') or ''}，{'★' * int(e.get('rarity') or 0) if e.get('rarity') else ''}）"]
        if e.get("skills"):
            parts.append("技能: " + "; ".join(str(s.get("name", "")) for s in e.get("skills", [])[:3]))
        return "；".join([p for p in parts if p])
    if entity and entity.get("found") is False:
        return f"未收录实体: {entity.get('message', '')}"
    # 文档问答
    if "answer" in result:
        return f"{result.get('answer', '')}（引用 {result.get('retrieved', 0)} 条）"
    # 向量统计
    if "stats" in result:
        s = result["stats"]
        return f"集合 {s.get('collection')}: 共 {s.get('total')} 块，孤儿块 {s.get('orphan_chunk_count')}（按文档 {s.get('by_doc', {})}）"
    if "collections" in result:
        return "；".join(f"{c['name']} {c['count']}块" for c in result["collections"])
    # 检索结果
    if "retrieval" in result:
        docs = result["retrieval"]
        return "；".join(f"{d.get('title')}" for d in docs[:3]) or "检索无结果"
    return json.dumps(result, ensure_ascii=False)[:300]


def synthesize(task: str, results: list[dict], use_llm: bool = True) -> str:
    """汇总各智能体结果（LLM 主路径，失败/禁用时结构化拼接）"""
    if use_llm and results:
        try:
            from app.agents.llm import get_chat_model

            transcript = "\n".join(
                f"[{r['index']}] {r['agent']}（{r['task']}）: {_summarize_result(r['result'])}" for r in results
            )
            resp = get_chat_model().invoke(
                [
                    {"role": "system", "content": _SYNTHESIZE_INSTRUCTION},
                    {"role": "user", "content": f"用户请求：{task}\n\n子智能体结果：\n{transcript}"},
                ]
            )
            answer = (resp.content or "").strip()
            if answer:
                return answer
        except Exception as e:  # noqa: BLE001
            logger.warning("[a2a] LLM 汇总失败，走结构化拼接: %s", e)
    lines = [f"[{r['agent']}] {_summarize_result(r['result'])}" for r in results]
    return "\n".join(lines) if lines else "（无子任务可执行）"


# ---------- 对外入口 ----------


def run(task: str, use_llm: bool = True) -> dict:
    """A2A 全流程：分解 → 派发 → 汇总。返回结构化结果（含子任务明细，可观测）"""
    runs = decompose(task, use_llm=use_llm)
    results = dispatch(runs)
    answer = synthesize(task, results, use_llm=use_llm)
    return {
        "task": task,
        "subtasks": runs,
        "results": results,
        "answer": answer,
    }
