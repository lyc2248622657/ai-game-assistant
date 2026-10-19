"""数据层与工具层修复的回归测试。

覆盖本轮修掉的真实缺陷：
  1. 静态库遮蔽动态缓存（同名条目取到残缺的静态版）
  2. 动态缓存解析失败时被整份覆盖
  3. 落盘守卫（空/大幅缩水拒写）
  4. 天赋材料按"全部 skills"计数（含被动）导致约 2 倍高估
  5. 方舟养成计划混入原神材料口径
  6. 养成计划删除缺少会话归属校验
  7. 配队成员 `character_胡桃` 与角色名匹配不上
  8. 模型输出 JSON 的贪婪正则解析
  9. 资料上下文无预算（prompt 膨胀）
"""
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.core.llm_json import extract_json  # noqa: E402


class _Game:
    """最小 Game 替身：只需要 data_dir / game_id / name / collection"""

    def __init__(self, data_dir: Path, game_id: str = "genshin"):
        self.data_dir = Path(data_dir)
        self.game_id = game_id
        self.name = game_id
        self.collection = f"{game_id}_kb"


def _write(path: Path, items) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")


# ---------- 1. 静态 / 动态合并 ----------
def test_dynamic_overrides_static_and_dedups_by_name(tmp_path):
    from app.tools.game_entity import load_entries

    _write(tmp_path / "characters.json", [
        {"id": "char_银灰", "type": "character", "name": "银灰", "summary": "旧静态版"},
        {"id": "char_other", "type": "character", "name": "另一人"},
    ])
    _write(tmp_path / "dynamic" / "characters.json", [
        {"id": "char_银灰", "type": "character", "name": "银灰", "summary": "新动态版", "skills": [{"name": "x"}]},
    ])
    items = load_entries(tmp_path, "character")
    by_name = {e["name"]: e for e in items}
    assert len(items) == 2, "同名条目应合并成一条"
    assert by_name["银灰"]["summary"] == "新动态版"
    assert by_name["银灰"].get("skills")


def test_load_all_entries_covers_teams(tmp_path):
    from app.tools.game_entity import load_all_entries

    _write(tmp_path / "teams.json", [{"id": "team_a", "type": "team", "name": "某队", "members": []}])
    _write(tmp_path / "characters.json", [{"id": "char_a", "type": "character", "name": "某人"}])
    names = {e["name"] for e in load_all_entries(_Game(tmp_path))}
    assert names == {"某队", "某人"}


# ---------- 2/3. 动态缓存写入守卫 ----------
def test_save_dynamic_refuses_to_clobber_corrupt_file(tmp_path):
    from app.tools.game_entity import _save_dynamic

    dyn = tmp_path / "dynamic"
    dyn.mkdir(parents=True)
    bad = dyn / "characters.json"
    bad.write_text("{ 这不是合法 JSON", encoding="utf-8")

    ok = _save_dynamic(_Game(tmp_path), "character", {"id": "char_x", "type": "character", "name": "新角色"})

    assert ok is False, "解析失败时必须放弃写入"
    assert bad.read_text(encoding="utf-8") == "{ 这不是合法 JSON", "原文件不能被覆盖"


def test_save_dynamic_replaces_same_name(tmp_path):
    from app.tools.game_entity import _save_dynamic

    _write(tmp_path / "dynamic" / "characters.json", [
        {"id": "char_a", "type": "character", "name": "甲", "summary": "旧"},
    ])
    ok = _save_dynamic(_Game(tmp_path), "character", {"id": "char_a2", "type": "character", "name": "甲", "summary": "新"})
    assert ok is True
    items = json.loads((tmp_path / "dynamic" / "characters.json").read_text(encoding="utf-8"))
    assert len(items) == 1, "同名条目应替换而非追加"
    assert items[0]["summary"] == "新"


def test_write_json_guarded_rejects_empty_and_shrink(tmp_path):
    from scripts.safe_io import write_json_guarded

    p = tmp_path / "d.json"
    p.write_text(json.dumps([{"i": i} for i in range(10)]), encoding="utf-8")

    assert write_json_guarded(p, []) is False, "空结果不得覆盖非空文件"
    assert write_json_guarded(p, [{"i": 1}]) is False, "缩水到 10% 应被拒绝"
    assert len(json.loads(p.read_text(encoding="utf-8"))) == 10

    assert write_json_guarded(p, [{"i": i} for i in range(9)]) is True
    assert len(json.loads(p.read_text(encoding="utf-8"))) == 9


# ---------- 4/5. 养成材料口径 ----------
def test_build_materials_skips_genshin_constants_for_arknights():
    from app.tools.build_plan import build_materials

    assert build_materials({"element": "火", "skills": []}, 90, 10, game_id="arknights") == []
    genshin = build_materials({"element": "火", "skills": []}, 90, 10, game_id="genshin")
    assert any(m["name"] == "摩拉" for m in genshin)


def test_build_materials_counts_only_active_talents():
    from app.tools.build_plan import TALENT_BOOKS, build_materials

    entity = {
        "element": "火",
        "skills": [
            {"name": "普攻", "type": "normal"},
            {"name": "战技", "type": "skill"},
            {"name": "爆发", "type": "burst"},
            {"name": "被动1", "type": "passive"},
            {"name": "被动2", "type": "passive"},
            {"name": "生活", "type": "utility"},
        ],
    }
    mats = build_materials(entity, 90, 10)
    teach = next(m for m in mats if m["name"] == "天赋书·教导")
    expected = TALENT_BOOKS[10][0] * 3
    assert teach["count"] == expected, f"应只按 3 个主动天赋计，实际 {teach['count']} vs {expected}"


# ---------- 6. 计划删除归属校验 ----------
def test_plan_store_delete_requires_ownership(tmp_path):
    from app.tools.build_plan import PlanStore

    store = PlanStore(db_path=str(tmp_path / "p.db"))
    pid = store.save("sess-a", "genshin", "胡桃", "90", {"materials": []})

    assert store.delete(pid, session_id="sess-b") is False, "跨会话删除必须失败"
    assert len(store.list_by_session("sess-a")) == 1
    assert store.delete(pid, session_id="sess-a") is True
    assert store.list_by_session("sess-a") == []


# ---------- 7. 引用前缀归一 ----------
def test_norm_ref_strips_prefix():
    from app.tools.game_entity import _norm_ref

    assert _norm_ref("character_胡桃") == "胡桃"
    assert _norm_ref("char_银灰") == "银灰"
    assert _norm_ref("胡桃") == "胡桃"


def test_related_gear_matches_prefixed_members(tmp_path):
    from app.tools.game_entity import _related_gear

    _write(tmp_path / "teams.json", [
        {"id": "team_a", "type": "team", "name": "胡桃蒸发队", "members": ["character_胡桃", "character_行秋"]},
    ])
    rel = _related_gear(_Game(tmp_path), "胡桃")
    assert [r["name"] for r in rel] == ["胡桃蒸发队"]


# ---------- 8. JSON 抽取 ----------
@pytest.mark.parametrize("raw,expected", [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": 2}\n```', {"a": 2}),
    ('好的，结果如下：{"a": 3}\n以上。', {"a": 3}),
    ('{"a": 4} 还有 {"b": 5}', {"a": 4}),
    ('前置 {不是json} 然后 {"a": 6}', {"a": 6}),
])
def test_extract_json(raw, expected):
    assert extract_json(raw) == expected


def test_extract_json_returns_none_when_absent():
    assert extract_json("完全没有 JSON") is None
    assert extract_json("") is None


# ---------- 10. 评测规则判定口径 ----------
def test_rule_judge_requires_key_points():
    """numeric 判定必须同时命中 ground_truth 与 key_points（旧口径只看 gt 子串，易虚高）"""
    from scripts.eval.eval_runner import _rule_judge

    case = {"ground_truth": "5星", "key_points": ["哥伦比娅", "5星"]}
    assert _rule_judge(case, "哥伦比娅是五星角色，适合蒸发队")[0] is True, "中文数字应等价于 5"
    assert _rule_judge(case, "哥伦比娅是四星角色")[0] is False
    # 只提到"五星"但没提实体 → 不算命中（旧口径会误判为正确）
    assert _rule_judge(case, "这个角色是五星，很强")[0] is False


def test_rule_judge_reports_missing():
    from scripts.eval.eval_runner import _rule_judge

    hit, missing = _rule_judge({"ground_truth": "冰", "key_points": ["薇斯娜", "冰"]}, "薇斯娜是火元素")
    assert hit is False
    assert any("冰" in m for m in missing)


# ---------- 9. 资料上下文预算 ----------
def test_build_materials_respects_budget():
    from app.agents.graph import _MATERIALS_TOTAL_MAX, _build_materials

    docs = [{"title": f"条目{i}", "content": "长" * 5000} for i in range(20)]
    materials = _build_materials({"retrieved_docs": docs, "tool_results": []})
    total = sum(len(m) for m in materials if not m.startswith("[提示]"))
    assert total <= _MATERIALS_TOTAL_MAX
    assert any(m.startswith("[提示]") for m in materials), "超限时应显式标注省略条数"
