"""信息补全逻辑单测：只补缺失字段 / 不覆盖已有值 / wiki 失败静默"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.knowledge.games import registry  # noqa: E402
from app.tools import game_entity as ge  # noqa: E402


def _game():
    return registry.get_game("genshin")


def test_enhance_fills_missing_fields(monkeypatch):
    """缺失的 skills/constellations 从 wiki 补全并写回缓存"""
    saved = []

    def fake_fetch(entry_type, name, game):
        return {"skills": "技能A；技能B", "constellations": "命座1", "debut_date": "2026-01-01"}

    monkeypatch.setattr(ge, "_fetch_official", fake_fetch)
    monkeypatch.setattr(ge, "_save_dynamic", lambda g, t, e: saved.append(e))

    out = {"id": "character_测试", "name": "测试", "rarity": 5}
    meta = {"source": "dynamic"}
    ge._enhance_entry_from_wiki(_game(), "character", "测试", out, meta)
    assert out["skills"] == "技能A；技能B"
    assert out["constellations"] == "命座1"
    assert saved and saved[0]["name"] == "测试"


def test_enhance_never_overwrites_existing(monkeypatch):
    """已有字段不被 wiki 覆盖（只补缺失）"""
    out = {"id": "character_测试", "name": "测试", "skills": "已有技能"}

    def fake_fetch(entry_type, name, game):
        return {"skills": "wiki技能（不应覆盖）", "constellations": "命座1"}

    monkeypatch.setattr(ge, "_fetch_official", fake_fetch)
    saved = []
    monkeypatch.setattr(ge, "_save_dynamic", lambda g, t, e: saved.append(e))
    ge._enhance_entry_from_wiki(_game(), "character", "测试", out, {"source": "dynamic"})
    assert out["skills"] == "已有技能"  # 未被覆盖
    assert out["constellations"] == "命座1"
    assert saved


def test_enhance_wiki_failure_silent(monkeypatch):
    """wiki 获取失败 → 静默跳过，不抛异常不改数据"""
    out = {"id": "character_测试", "name": "测试", "skills": "已有"}

    def boom_fetch(entry_type, name, game):
        raise TimeoutError("wiki 超时")

    monkeypatch.setattr(ge, "_fetch_official", boom_fetch)
    ge._enhance_entry_from_wiki(_game(), "character", "测试", out, {"source": "dynamic"})
    assert out["skills"] == "已有"  # 数据未变


def test_enhance_ignores_non_character():
    """武器/圣遗物等非角色类型不做字段补全"""
    out = {"id": "weapon_测试", "name": "测试"}
    ge._enhance_entry_from_wiki(_game(), "weapon", "测试", out, {"source": "dynamic"})
    assert "skills" not in out


def test_enhance_no_missing_fields_noop(monkeypatch):
    """字段齐全时不触发 wiki 请求"""
    fetched = []

    def fake_fetch(entry_type, name, game):
        fetched.append(name)
        return {}

    monkeypatch.setattr(ge, "_fetch_official", fake_fetch)
    out = {"id": "character_测试", "name": "测试", "skills": "有", "constellations": "有"}
    ge._enhance_entry_from_wiki(_game(), "character", "测试", out, {"source": "dynamic"})
    assert fetched == []  # 无缺失字段 → 不请求 wiki
