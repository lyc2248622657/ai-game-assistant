"""知识包数据校验：必填字段 / id 唯一 / 交叉引用有效性 / 图片字段

用法：
    python scripts/validate_data.py --game genshin          # 严格模式（默认）
    python scripts/validate_data.py --game genshin --loose  # 宽松模式（引用缺失仅警告）

扩展机制说明：
    - 新字段/extra 自由增加，不校验未知字段；
    - 新模板类型 = 目录下新 JSON 文件，本脚本自动识别其 type 并纳入引用校验。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.logging import setup_logging  # noqa: E402
from app.knowledge.games import registry  # noqa: E402

setup_logging()
logger = __import__("app.core.logging", fromlist=["get_logger"]).get_logger("validate")

# 各类型必填字段
REQUIRED_FIELDS = {
    "character": ["id", "type", "name", "element", "weapon_type", "rarity", "role", "region"],
    "weapon": ["id", "type", "name", "category", "rarity", "sub_stat"],
    "artifact": ["id", "type", "name", "two_piece", "four_piece"],
    "material": ["id", "type", "name", "category"],
    "food": ["id", "type", "name", "food_type", "effect", "obtain"],
    "team": ["id", "type", "name", "members"],
}

# 引用字段：字段名 -> (目标类型, 是否数组)
REFERENCE_FIELDS = {
    "character": {"special_food": ("food", False)},
    "weapon": {"recommended": ("character", True)},
    "artifact": {"recommended": ("character", True)},
    "food": {"owner_character": ("character", False), "prototype_food": ("food", False)},
    "team": {"members": ("character", True)},
}


def main():
    parser = argparse.ArgumentParser(description="知识包数据校验")
    parser.add_argument("--game", required=True, help="游戏 id")
    parser.add_argument("--loose", action="store_true", help="宽松模式：引用缺失仅警告")
    args = parser.parse_args()

    game = registry.get_game(args.game)
    data_dir: Path = game.data_dir
    if not data_dir.exists():
        logger.error("数据目录不存在: %s", data_dir)
        sys.exit(1)

    # 1. 收集全部条目
    entries: list[dict] = []
    files = sorted(data_dir.glob("*.json"))
    for f in files:
        if f.name in ("TEMPLATE.md", "meta.json"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else [data]
        entries.extend(items)

    errors, warnings = [], []

    # 2. id 唯一性 + 索引
    by_id: dict[str, dict] = {}
    for e in entries:
        if not isinstance(e, dict):
            errors.append(f"条目不是对象: {e}")
            continue
        eid = e.get("id", "")
        if not eid:
            errors.append(f"缺 id: {e.get('name', '?')}")
            continue
        if eid in by_id:
            errors.append(f"id 重复: {eid}")
        by_id[eid] = e

    # 3. 必填字段 + type 一致性
    type_of_file: dict[str, str] = {
        "characters.json": "character",
        "weapons.json": "weapon",
        "artifacts.json": "artifact",
        "materials.json": "material",
        "foods.json": "food",
        "teams.json": "team",
    }
    for f in files:
        if f.name in type_of_file and f.name != "TEMPLATE.md":
            expected = type_of_file[f.name]
            data = json.loads(f.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else [data]
            for e in items:
                if e.get("type") != expected:
                    errors.append(f"{f.name} 中条目 type={e.get('type')} 与文件类型 {expected} 不一致: {e.get('name')}")

    for e in entries:
        t = e.get("type")
        for field in REQUIRED_FIELDS.get(t, ["id", "type", "name"]):
            if field not in e or e[field] in ("", None):
                errors.append(f"[{e.get('id')}] 缺必填字段: {field}")

    # 4. 交叉引用校验
    for e in entries:
        t = e.get("type")
        for field, (target_type, is_array) in REFERENCE_FIELDS.get(t, {}).items():
            value = e.get(field)
            if value in ("", None):
                continue
            targets = value if is_array else [value]
            for ref in targets:
                target = by_id.get(ref)
                if target is None:
                    msg = f"[{e.get('id')}] 引用不存在: {field}={ref}"
                    (warnings if args.loose else errors).append(msg)
                elif target.get("type") != target_type:
                    msg = f"[{e.get('id')}] 引用类型不符: {field}={ref} (期望 {target_type}, 实际 {target.get('type')})"
                    (warnings if args.loose else errors).append(msg)

    # 5. 图片字段统计（不报错，提示待补充）
    missing_images = [e.get("id") for e in entries if not e.get("image")]

    # 输出
    print(f"文件数: {len(files)} | 条目总数: {len(entries)} | 类型: {sorted(t for t in {e.get('type') for e in entries} if t)}")
    print(f"缺图片条目: {len(missing_images)}")
    if errors:
        print(f"\n错误 {len(errors)} 条:")
        for m in errors[:30]:
            print("  ✗", m)
        sys.exit(1)
    if warnings:
        print(f"\n警告 {len(warnings)} 条（宽松模式）:")
        for m in warnings[:30]:
            print("  ⚠", m)
    print("✓ 校验通过")


if __name__ == "__main__":
    main()
