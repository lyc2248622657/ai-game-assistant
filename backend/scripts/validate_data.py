"""知识包数据校验：必填字段 / id 唯一 / type 一致 / 交叉引用有效性 / 图片字段

用法：
    python scripts/validate_data.py --game genshin           # 默认：硬错误才失败
    python scripts/validate_data.py --game genshin --strict  # 警告也失败（CI 建议用这个）
    python scripts/validate_data.py --game arknights

相对旧版的三处修正：
  1. `glob("*.json")` → `rglob("*.json")`：dynamic/ 占 98% 数据，此前从未被校验；
  2. 引用字段名 `recommended` → 同时支持 `recommended` / `recommended_characters`；
  3. 引用解析改为"前缀归一后按名称匹配"：数据里存在 `char_x` / `character_x` / `x`
     多套 id 规则，直接按 id 查会把大量合法引用误判为悬空。
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.logging import setup_logging  # noqa: E402
from app.knowledge.games import registry  # noqa: E402
from app.tools.game_entity import FILE_BY_TYPE  # noqa: E402

setup_logging()
logger = __import__("app.core.logging", fromlist=["get_logger"]).get_logger("validate")

FILE_TYPE = {v: k for k, v in FILE_BY_TYPE.items()}

# 各类型必填字段（缺失记为警告：方舟与原神字段口径不同，硬失败会误伤）
REQUIRED_FIELDS = {
    "character": ["id", "type", "name"],
    "weapon": ["id", "type", "name"],
    "artifact": ["id", "type", "name"],
    "material": ["id", "type", "name"],
    "food": ["id", "type", "name"],
    "team": ["id", "type", "name", "members"],
}

# 引用字段：(字段名, 目标类型)
REFERENCE_FIELDS = {
    "character": [("special_food", "food")],
    "weapon": [("recommended", "character"), ("recommended_characters", "character")],
    "artifact": [("recommended", "character"), ("recommended_characters", "character")],
    "food": [("owner_character", "character"), ("prototype_food", "food")],
    "team": [("members", "character")],
}

_PREFIX_RE = re.compile(r"^(character|char|weapon|artifact|material|food|team)_")


def _norm(ref: str) -> str:
    """引用归一：去前缀 + 去空白，用于跨 id 规则比对"""
    return _PREFIX_RE.sub("", str(ref or "").strip())


def _iter_files(data_dir: Path) -> list[Path]:
    out = []
    for p in sorted(data_dir.rglob("*.json")):
        name = p.name
        if name in ("meta.json",) or ".backup" in name or name.startswith("_"):
            continue
        out.append(p)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="知识包数据校验")
    parser.add_argument("--game", required=True, help="游戏 id")
    parser.add_argument("--strict", action="store_true", help="警告也视为失败（CI 用）")
    parser.add_argument("--loose", action="store_true", help="保留参数：旧版语义（默认已不因警告失败）")
    args = parser.parse_args()

    game = registry.get_game(args.game, require_enabled=False)
    data_dir: Path = game.data_dir
    if not data_dir.exists():
        logger.error("数据目录不存在: %s", data_dir)
        return 1

    files = _iter_files(data_dir)
    hard: list[str] = []
    warn: list[str] = []
    alias_refs: list[str] = []
    entries: list[dict] = []
    layers: dict[str, str] = {}   # id -> layer
    per_file: dict[str, int] = {}

    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            hard.append(f"{f.relative_to(data_dir)}: JSON 解析失败 {e}")
            continue
        items = data if isinstance(data, list) else [data]
        items = [e for e in items if isinstance(e, dict)]
        layer = "dynamic" if "dynamic" in f.parts else "static"
        per_file[str(f.relative_to(data_dir))] = len(items)
        expected = FILE_TYPE.get(f.name)
        for e in items:
            if expected and e.get("type") != expected:
                hard.append(f"{f.name}: type={e.get('type')} 与文件类型 {expected} 不一致（{e.get('name')}）")
            eid = str(e.get("id") or "")
            if eid:
                prev = layers.get(eid)
                if prev == layer:
                    hard.append(f"同层 id 重复: {eid}（{layer}）")
                elif prev and prev != layer:
                    # 静态 + 动态同 id：属预期的分层结构，动态会在读取时覆盖静态
                    warn.append(f"id 跨层重复（静态被 dynamic 覆盖）: {eid}")
                layers.setdefault(eid, layer)
            entries.append(e)

    # 建立引用索引：原始 id + 归一名称 + 归一 id
    index: dict[str, dict] = {}
    for e in entries:
        for key in (str(e.get("id") or ""), _norm(str(e.get("id") or "")), str(e.get("name") or ""), _norm(str(e.get("name") or ""))):
            if key:
                index.setdefault(key, e)

    for e in entries:
        eid = e.get("id") or e.get("name") or "?"
        t = e.get("type")
        if not e.get("id"):
            hard.append(f"缺 id: {e.get('name', '?')}")
        for field in REQUIRED_FIELDS.get(t, ["id", "type", "name"]):
            if e.get(field) in ("", None):
                warn.append(f"[{eid}] 缺字段: {field}")
        for field, target_type in REFERENCE_FIELDS.get(t, []):
            value = e.get(field)
            if value in ("", None):
                continue
            refs = value if isinstance(value, list) else [value]
            for ref in refs:
                target = index.get(str(ref)) or index.get(_norm(str(ref)))
                if target is None:
                    msg = f"[{eid}] 引用悬空: {field}={ref}"
                    # 纯 ASCII 引用（如拼音 hutao / 英文别名）单独归类，避免刷屏
                    if re.fullmatch(r"[A-Za-z0-9_\-]+", str(ref)):
                        alias_refs.append(msg)
                    else:
                        warn.append(msg)
                elif target.get("type") != target_type:
                    warn.append(f"[{eid}] 引用类型不符: {field}={ref}（期望 {target_type}）")

    no_image = sum(1 for e in entries if not (e.get("image") or e.get("image_url")))

    print(f"游戏: {args.game} | 文件 {len(files)} 个 | 条目 {len(entries)} 条")
    print("  分文件: " + ", ".join(f"{k}={v}" for k, v in per_file.items()))
    print(f"  缺图片: {no_image} 条")
    if hard:
        print(f"\n硬错误 {len(hard)} 条（必须修复）:")
        for m in hard[:30]:
            print("  ✗", m)
    if warn:
        print(f"\n警告 {len(warn)} 条（数据质量提示）:")
        for m in warn[:20]:
            print("  ⚠", m)
        if len(warn) > 20:
            print(f"  … 其余 {len(warn) - 20} 条省略")
    if alias_refs:
        print(f"\n拼音/别名类悬空引用 {len(alias_refs)} 条（字段值不是名称也不是 id，建议统一为 id）:")
        for m in alias_refs[:5]:
            print("  ⚠", m)
        if len(alias_refs) > 5:
            print(f"  … 其余 {len(alias_refs) - 5} 条省略")
    if hard or (args.strict and (warn or alias_refs)):
        return 1
    print("\n✓ 校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
