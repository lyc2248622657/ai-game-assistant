"""批量补全明日方舟干员缺失字段（稀有度/职业/分支/简介/特性）。

数据源：PRTS wiki 官方字段（_fetch_official → parse_template_fields 平衡匹配，已修复稀有度/职业漏提取）。
只补缺失字段，不覆盖已有值；wiki 获取失败静默跳过（记录输出）。

用法：
  python scripts/backfill_characters.py --since 2026-01-01            # 补该日期后实装且缺失的干员
  python scripts/backfill_characters.py --since 2025-01-01 --all      # 全部缺失字段条目
  python scripts/backfill_characters.py --since 2026-07-01 --dry-run  # 只看待补清单
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core import key_manager  # noqa: E402
from app.knowledge.games import registry  # noqa: E402
from app.tools.game_entity import _fetch_official  # noqa: E402

# PRTS 稀有度存 0-5（0=1星 … 5=6星），dynamic 用 1-6 星制
_RARITY_OFFSET = 1


def _apply_app_key() -> None:
    """把应用内设置（settings.json）的 key 注入环境变量（兼容旧 LLM 链路）"""
    if os.environ.get("DEEPSEEK_API_KEY"):
        return
    kv = key_manager.load_saved()
    if kv and kv[1] and not str(kv[1]).startswith("sk-xxx"):
        os.environ["DEEPSEEK_API_KEY"] = kv[1]


def _parse_dt(s) -> tuple[int, int, int] | None:
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(s or ""))
    if not m:
        return None
    try:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:  # noqa: BLE001
        return None


def _is_cn(v) -> bool:
    """职业/分支应为中文开头（PRTS 均为中文；英文/空视为未规范）"""
    return bool(v) and bool(re.match(r"^[\u4e00-\u9fff（(]", str(v)))


def _missing_fields(e: dict) -> list[str]:
    need: list[str] = []
    if e.get("rarity") in (None, "", "null"):
        need.append("rarity")
    if not _is_cn(e.get("role")):
        need.append("role")
    if not _is_cn(e.get("weapon_type")):
        need.append("weapon_type")
    if not e.get("characteristic") or len(str(e.get("characteristic")).strip()) < 6:
        need.append("characteristic")
    if not e.get("summary") or len(str(e.get("summary")).strip()) < 10:
        need.append("summary")
    return need


def _build_summary(e: dict) -> str:
    """按库内格式拼接 summary：{稀有度}星{职业}·{分支}，{特性}"""
    parts = []
    r = e.get("rarity")
    role = e.get("role")
    wt = e.get("weapon_type")
    head = []
    if r not in (None, ""):
        head.append(f"{r}星")
    if _is_cn(role):
        head.append(role)
    if _is_cn(wt):
        head.append(f"·{wt}")
    if head:
        parts.append("".join(head))
    if e.get("characteristic"):
        parts.append(e["characteristic"])
    return "，".join(parts) if parts else ""


def main() -> None:
    ap = argparse.ArgumentParser(description="补全方舟干员缺失字段（PRTS 官方源）")
    ap.add_argument("--since", default="2025-01-01", help="仅补该日期后实装且缺失的干员，格式 YYYY-MM-DD")
    ap.add_argument("--limit", type=int, default=0, help="最多处理条数（0=不限）")
    ap.add_argument("--dry-run", action="store_true", help="仅列出待补清单")
    ap.add_argument("--all", action="store_true", help="忽略 since 限制（全量补缺）")
    args = ap.parse_args()
    _apply_app_key()

    game = registry.get_game("arknights")
    path = game.data_dir / "dynamic" / "characters.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else data.get("characters") or list(data.values())[0]

    since = (0, 0, 0) if args.all else tuple(int(x) for x in args.since.split("-"))
    targets: list[tuple[int, str, list[str]]] = []
    for idx, e in enumerate(items):
        dt = _parse_dt(e.get("debut_date")) or (0, 0, 0)
        if dt < since:
            continue
        need = _missing_fields(e)
        if need:
            targets.append((idx, e.get("name", "?"), need))
    print(f"待补全 {len(targets)} 条（{'全量' if args.all else args.since + ' 后'}实装且缺失字段）")
    for _, name, need in targets[:30]:
        print(f"  - {name}: {', '.join(need)}")
    if args.dry_run:
        return
    if not targets:
        return

    done = ok = fail = 0
    for idx, name, need in targets:
        if args.limit and done >= args.limit:
            print(f"达 limit={args.limit}，停止")
            break
        done += 1
        try:
            wf = _fetch_official("character", name, game)
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"  ✗ {name}: 抓取异常 {e}")
            continue
        if not wf:
            fail += 1
            print(f"  ✗ {name}: wiki 无字段（页面不存在或结构不同）")
            continue

        changed: list[str] = []
        if "rarity" in need and "稀有度" in wf:
            try:
                items[idx]["rarity"] = int(wf["稀有度"]) + _RARITY_OFFSET
                changed.append("rarity")
            except (TypeError, ValueError):  # noqa: BLE001
                pass
        if "role" in need and _is_cn(wf.get("职业")):
            items[idx]["role"] = wf["职业"].strip()
            changed.append("role")
        if "weapon_type" in need and _is_cn(wf.get("分支")):
            items[idx]["weapon_type"] = wf["分支"].strip()
            changed.append("weapon_type")
        if "characteristic" in need and wf.get("特性"):
            items[idx]["characteristic"] = wf["特性"].strip()
            changed.append("characteristic")
        if "summary" in need:
            items[idx]["summary"] = _build_summary(items[idx])
            if len(str(items[idx].get("summary", "")).strip()) >= 10:
                changed.append("summary")

        if changed:
            ok += 1
            print(f"  ✓ {name}: 补全 {', '.join(changed)}")
        else:
            fail += 1
            print(f"  - {name}: 无可用新值")

    if ok:
        payload = items if isinstance(data, list) else {**data, "characters": items}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写回 {path}（成功 {ok} / 失败 {fail} / 总数 {done}）")
    else:
        print("\n无任何补全，未写回文件")


if __name__ == "__main__":
    main()
