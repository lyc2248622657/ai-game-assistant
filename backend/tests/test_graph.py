"""Agent 图节点纯逻辑单测：委派路由 / 动态重规划 / 建议生成 / 材料聚合

不启动服务、不联网：直接调用图内的纯函数与构建逻辑。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.graph import (  # noqa: E402
    _build_suggestions,
    _build_task_plan_prompt,
    _replan_signals,
    _resolve_delegate,
    build_graph,
    decide_after_retrieve,
    decide_replan,
)
from app.agents.prompts import build_subagent_system_prompt  # noqa: E402


def test_graph_builds():
    """状态图可编译（节点/边齐全：主管委派 + 子代理执行 + 动态重规划）"""
    g = build_graph()
    for node in ("supervisor", "route", "retrieve", "tool", "replan", "synthesize", "reflect", "fallback"):
        assert node in g.nodes, f"缺少节点 {node}"


# ---------- 多智能体协作：委派解析（纯函数） ----------
def test_resolve_delegate_genshin_entity():
    assert _resolve_delegate("genshin", "entity") == "genshin_agent"


def test_resolve_delegate_arknights_entity():
    assert _resolve_delegate("arknights", "entity") == "arknights_agent"


def test_resolve_delegate_knowledge_domain():
    assert _resolve_delegate("genshin", "knowledge") == "knowledge_agent"
    assert _resolve_delegate("arknights", "knowledge") == "knowledge_agent"
    assert _resolve_delegate("", "knowledge") == "knowledge_agent"


def test_resolve_delegate_explicit_wins():
    """显式委派优先于 domain+game 推断"""
    assert _resolve_delegate("arknights", "entity", "knowledge_agent") == "knowledge_agent"
def test_resolve_delegate_event_domain():
    """事件域（活动/卡池/维护排期）按游戏委派：genshin→原神子代理，arknights→方舟子代理"""
    assert _resolve_delegate("genshin", "event") == "genshin_agent"
    assert _resolve_delegate("arknights", "event") == "arknights_agent"
    assert _resolve_delegate("", "event") == "knowledge_agent"
    # 显式委派优先
    assert _resolve_delegate("genshin", "event", "knowledge_agent") == "knowledge_agent"


def test_subagent_prompt_injects_identity():
    """子代理 system prompt 注入委派身份（多智能体叙事；1.1 后身份由注册表 agent_label 派生）"""
    p = build_subagent_system_prompt("genshin_agent", "原神")
    assert "原神子代理" in p
    assert "主管智能体委派" in p
    # 注册表驱动的身份：新增游戏登记后，其 agent_id 自动出现在角色表
    from app.agents.prompts import SUBAGENT_ROLES

    assert "genshin_agent" in SUBAGENT_ROLES and "arknights_agent" in SUBAGENT_ROLES
    assert "knowledge_agent" in SUBAGENT_ROLES


# ---------- 动态重规划：规则预检（纯函数） ----------
def _replan_state(subtasks, tool_results):
    return {"subtasks": subtasks, "tool_results": tool_results}


def test_replan_signals_all_done():
    """全部子任务对应工具已执行且无失败 → 无需重规划"""
    st = _replan_state(
        [{"task": "配队", "suggested_tool": "analyze_teams"}],
        [{"name": "analyze_teams", "result": {"found": True, "teams": []}}],
    )
    pending, failed = _replan_signals(st)
    assert pending == [] and not failed


def test_replan_signals_pending_tool():
    """子任务建议工具未被调用 → 触发补充计划"""
    st = _replan_state(
        [{"task": "配队", "suggested_tool": "analyze_teams"},
         {"task": "攻略", "suggested_tool": "search_guides"}],
        [{"name": "analyze_teams", "result": {"found": True, "teams": []}}],
    )
    pending, failed = _replan_signals(st)
    assert [p["task"] for p in pending] == ["攻略"]


def test_replan_signals_failed_result():
    """工具返回未收录/错误 → 触发补充计划"""
    st = _replan_state(
        [{"task": "实体", "suggested_tool": "query_game_entity"}],
        [{"name": "query_game_entity", "result": {"found": False}}],
    )
    pending, failed = _replan_signals(st)
    assert failed


def test_decide_replan_loops_once():
    """重规划后回 tool 二次执行；已达上限则进入汇总（不会死循环）"""
    assert decide_replan({"replan_needed": True}) == "tool"
    assert decide_replan({"replan_needed": False}) == "synthesize"


def _suggestions_state(gid: str, etype: str, ename: str) -> dict:
    return {
        "game_id": gid,
        "plan_entity": {"type": etype, "name": ename},
        "tool_results": [{"result": {"found": True, "entity": {"name": ename}}}],
    }


def test_suggestions_arknights_character():
    sug = _build_suggestions(_suggestions_state("arknights", "character", "珊比"))
    assert "查看珊比适配队伍" in sug
    assert "查看珊比精英化材料总需求统计" in sug
    assert "查看珊比攻略视频" in sug


def test_suggestions_genshin_character():
    sug = _build_suggestions(_suggestions_state("genshin", "character", "那维莱特"))
    assert any("适配队伍" in s for s in sug)
    assert any("攻略视频" in s for s in sug)


def test_suggestions_weapon_nonempty():
    sug = _build_suggestions(_suggestions_state("genshin", "weapon", "无工之剑"))
    assert any("推荐角色" in s for s in sug)


def test_suggestions_level_arknights():
    """关卡场景：生成攻略类型建议按钮（不依赖实体命中）"""
    sug = _build_suggestions({
        "game_id": "arknights",
        "plan_entity": {"type": "level", "name": "H8-4"},
    })
    assert any("摆完挂机" in s for s in sug)
    assert any("单核" in s for s in sug)
    assert any("高配" in s for s in sug)


def test_suggestions_level_with_type():
    """用户已指定攻略类型时置顶对应选项"""
    sug = _build_suggestions({
        "game_id": "arknights",
        "plan_entity": {"type": "level", "name": "H8-4"},
        "guide_type": "摆完挂机",
    })
    assert sug[0] == "H8-4摆完挂机攻略"


def test_decide_after_retrieve_empty_to_tool():
    """检索为空 → 自动转工具节点（P0-2 已实现）"""
    assert decide_after_retrieve({"task_type": "entity_query", "retrieved_docs": []}) == "tool"


def test_decide_after_retrieve_has_docs():
    assert decide_after_retrieve({"task_type": "entity_query", "retrieved_docs": [{"doc_id": "1", "content": "x"}]}) == "synthesize"


def test_task_plan_prompt_empty():
    """无子任务 → 不注入规划提示（兼容单意图）"""
    assert _build_task_plan_prompt([]) == ""


def test_task_plan_prompt_formats():
    """复合意图 → 生成带工具建议的规划提示（引导 LLM 自主执行）"""
    p = _build_task_plan_prompt([
        {"task": "配队", "description": "查询那维莱特推荐配队", "suggested_tool": "analyze_teams", "target": "那维莱特"},
        {"task": "攻略", "description": "找攻略视频", "suggested_tool": "search_guides", "target": "那维莱特"},
    ])
    assert "任务规划" in p
    assert "analyze_teams" in p
    assert "search_guides" in p
    assert "那维莱特" in p
