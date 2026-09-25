# -*- coding: utf-8 -*-
"""存量角色补全：对 dynamic/characters.json 现有条目，以原神官方 wiki 为主要依据
补全 birthday/constellations/skills(+数值表)，LLM 仅补 teams/role 等缺失推断字段。

用法：
    python scripts/backfill_official.py [--game genshin] [--limit N]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.knowledge.games import GameRegistry  # noqa: E402
from app.tools.game_entity import (  # noqa: E402
    _Lazy,
    _build_from_wiki,
    _fetch_official,
)
from scripts.generator.validator import Validator  # noqa: E402


def backfill(game, entry_type: str, limit: int = 0) -> tuple[int, int]:
    dyn_dir = game.data_dir / "dynamic"
    path = dyn_dir / "characters.json"
    if not path.exists():
        print("无动态缓存文件:", path)
        return 0, 0
    items = json.loads(path.read_text(encoding="utf-8"))
    llm = _Lazy.get_llm("")
    val = Validator(llm)
    updated = 0
    skipped = 0
    todo = items[:limit] if limit else items
    for i, entry in enumerate(todo, 1):
        name = entry.get("name", "")
        if not name:
            skipped += 1
            continue
        print(f"[{i}/{len(todo)}] {name} ...", flush=True)
        try:
            wf = _fetch_official(entry_type, name, game)
            if not wf:
                print(f"  -> wiki 无数据，跳过（保留原样）", flush=True)
                skipped += 1
                continue
            new_entry = _build_from_wiki(llm, entry_type, name, wf)
            # 保留原条目的 _meta 校验记录与已验证字段
            for k in ("title", "rarity", "element", "weapon_type", "role", "region",
                      "debut_version", "debut_date", "special_food", "summary", "obtain"):
                if new_entry.get(k) in (None, "") and entry.get(k):
                    new_entry[k] = entry[k]
            meta = entry.get("_meta") or {}
            meta["source"] = "official_wiki_backfill"
            meta["wiki_checked"] = True
            new_entry["_meta"] = meta
            # 校验（硬错误记录不阻断，尽量保留）
            errs = val.validate(entry_type, [new_entry], [name], set())
            hard = [x for x in errs if "引用不存在" not in x]
            if hard:
                print(f"  -> 校验警告: {hard[:3]}", flush=True)
            items[items.index(entry)] = new_entry
            updated += 1
        except Exception as e:  # noqa: BLE001
            print(f"  -> 异常: {e}", flush=True)
            skipped += 1
        time.sleep(0.3)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成：更新 {updated} 条，跳过 {skipped} 条")
    return updated, skipped


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--game", default="genshin")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    reg = GameRegistry()
    game = reg.get_game(args.game)
    backfill(game, "character", args.limit)
