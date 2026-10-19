"""养成规划工具单测：预算测算 / 材料清单 / 计划持久化闭环"""


from app.knowledge.games import registry
from app.tools.base import ToolContext
from app.tools.build_plan import (
    PITY_HARD,
    PITY_SOFT,
    BuildBuildPlanTool,
    PlanStore,
    SaveBuildPlanTool,
    build_primogem_budget,
)

_genshin = registry.get_game("genshin")
_build = BuildBuildPlanTool()
_save = SaveBuildPlanTool()


def _ctx(session_id: str | None = "sess-test-001") -> ToolContext:
    return ToolContext(_genshin, session_id=session_id)


def test_budget_enough_for_hard_pity():
    b = build_primogem_budget(30_000, 20, [{"title": "版本活动"}])
    assert b["total_est"] >= PITY_HARD
    assert "大保底" in b["conclusion"]


def test_budget_shortfall():
    b = build_primogem_budget(5_000, 5, [])
    assert b["total_est"] < PITY_SOFT
    assert "还差" in b["conclusion"]


def test_build_plan_genshin_hu_tao():
    plan = _build.run({"game": "genshin", "character": "胡桃"}, _ctx())
    assert plan.get("found") is True
    assert plan["character"] == "胡桃"
    assert plan["element"] == "火"
    # 材料清单：摩拉 + 经验书 + 火宝石
    names = [m["name"] for m in plan["materials"]]
    assert any("摩拉" in n for n in names)
    assert any("大英雄的经验" in n for n in names)
    assert any("燃愿玛瑙" in n for n in names)
    # 多步排期：至少 4 步
    assert len(plan["steps"]) >= 4
    # 跨源：预算结论存在
    assert "conclusion" in plan["budget"]


def test_build_plan_budget_passed():
    plan = _build.run({"game": "genshin", "character": "甘雨", "primogem_budget": 20_000}, _ctx())
    assert plan["budget"]["current"] == 20_000


def test_save_and_list_plan(tmp_path):
    store = PlanStore(str(tmp_path / "plans.db"))
    plan = _build.run({"game": "genshin", "character": "胡桃"}, _ctx())
    pid = store.save("sess-save-1", "genshin", "胡桃", "胡桃养成规划", plan)
    rows = store.list_by_session("sess-save-1")
    assert len(rows) == 1
    assert rows[0]["character"] == "胡桃"
    assert rows[0]["plan"]["character"] == "胡桃"
    assert store.delete(pid) is True
    assert store.list_by_session("sess-save-1") == []


def test_save_tool_requires_session():
    res = _save.run({"game": "genshin", "character": "胡桃"}, ToolContext(_genshin, session_id=None))
    assert res["saved"] is False
    assert "会话" in res["error"]


def test_save_tool_persists(tmp_path, monkeypatch):
    # 用临时库替代全局 plan_store
    from app.tools import build_plan as bp

    store = PlanStore(str(tmp_path / "plans2.db"))
    monkeypatch.setattr(bp, "plan_store", store)
    res = _save.run({"game": "genshin", "character": "胡桃", "goal": "5.0 抽卡+养成"}, _ctx())
    assert res["saved"] is True
    assert res["plan_id"] > 0
    assert store.list_by_session("sess-test-001")[0]["goal"] == "5.0 抽卡+养成"
