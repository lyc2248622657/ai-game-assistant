"""最近实装实体工具单测：倒序 / limit 钳制 / 同名去重 / 类型切换"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.knowledge.games import registry  # noqa: E402
from app.tools.base import ToolContext  # noqa: E402
from app.tools.game_entity import ListRecentEntitiesTool  # noqa: E402


def _ctx(game_id="genshin"):
    return ToolContext(registry.get_game(game_id))


def test_recent_default_limit_5():
    r = ListRecentEntitiesTool().run({"type": "character"}, _ctx())
    assert r["game"] == "genshin"
    assert r["count"] <= 5
    assert r["count"] > 0  # 原神 dynamic 数据源非空


def test_recent_limit_clamped():
    r = ListRecentEntitiesTool().run({"type": "character", "limit": 99}, _ctx())
    assert r["count"] <= 10  # 上限钳制 10
    r3 = ListRecentEntitiesTool().run({"type": "character", "limit": "abc"}, _ctx())
    assert r3["count"] == 5  # 非法值回退默认 5


def test_recent_sorted_desc_by_debut():
    r = ListRecentEntitiesTool().run({"type": "character", "limit": 10}, _ctx())
    dates = [e["debut_date"] for e in r["recent"] if e["debut_date"]]
    assert dates == sorted(dates, reverse=True)  # 最新在前


def test_recent_no_duplicate_names():
    r = ListRecentEntitiesTool().run({"type": "character", "limit": 10}, _ctx())
    names = [e["name"] for e in r["recent"]]
    assert len(names) == len(set(names))


def test_recent_arknights():
    r = ListRecentEntitiesTool().run({"type": "character"}, _ctx("arknights"))
    assert r["game"] == "arknights"
    assert r["count"] >= 1
