"""评测集格式校验：两游戏评测集 id 唯一 / type 合法 / key_points 非空 / 覆盖四种题型"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.eval.eval_runner import V2_SET, _load_cases  # noqa: E402

VALID_TYPES = {"entity", "knowledge", "edge", "complex"}


def test_eval_sets_total_and_unique():
    """all = 原神 30 + 方舟 20 = 50 题，id 全局唯一"""
    cases = _load_cases("all")
    assert len(cases) == 50
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "评测集 id 重复"


def test_eval_sets_shape_per_game():
    """每题：type 合法、key_points 非空、game_id 与加载目标一致"""
    for game in ("genshin", "arknights"):
        cases = _load_cases(game)
        assert cases, f"{game} 评测集为空"
        for c in cases:
            assert c["type"] in VALID_TYPES, f"{c['id']} type 非法: {c['type']}"
            assert c["key_points"], f"{c['id']} key_points 为空"
            assert c["game_id"] == game, f"{c['id']} game_id 错配"


def test_eval_types_distributed():
    """四种题型每种至少 4 题（保证指标分布可统计）"""
    cases = _load_cases("all")
    types = [c["type"] for c in cases]
    for t in VALID_TYPES:
        assert types.count(t) >= 4, f"类型 {t} 用例过少（{types.count(t)}）"


def test_eval_v2_set_format():
    """v2 扩展集（223 条）：id 唯一、type 合法、plan 用例带 ground_truth"""
    data = json.loads(V2_SET.read_text(encoding="utf-8"))
    ids = [c["id"] for c in data]
    assert len(ids) == len(set(ids)), "v2 评测集 id 重复"
    valid = VALID_TYPES | {"numeric", "plan"}
    for c in data:
        assert c["type"] in valid, f"{c['id']} type 非法: {c['type']}"
        assert c.get("key_points"), f"{c['id']} key_points 为空"
    plan = [c for c in data if c.get("type") == "plan"]
    assert len(plan) >= 3, "plan 用例不足"
    for c in plan:
        assert c.get("ground_truth"), f"{c['id']} plan 用例缺少 ground_truth"
