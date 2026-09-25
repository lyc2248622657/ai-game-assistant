"""每日预热脚本：从官方 wiki 拉取实体清单，将未收录的新实体补入动态缓存

用途（P2-1）：消除"冷启动未收录"——新角色/干员实装后无需用户先问，后台自动补全。
触发：本地定时任务（Windows 任务计划 / doubao 定时任务）或 GitHub Actions 云端 CI（备选）。

限速：WikiClient 内置全局限流（1 req/s + 退避），无需额外处理。
用法：python scripts/crawler/prewarm.py [genshin|arknights] [--limit 300] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.knowledge.games import registry  # noqa: E402
from app.tools.game_entity import _Lazy, FILE_BY_TYPE, generate_with_verification, load_entries  # noqa: E402

# 各游戏实体清单查询（SMW ask）
GAME_QUERIES = {
    "genshin": {"character": "[[分类:角色]]"},
    "arknights": {"character": "[[分类:干员]]"},
}

# 名称清洗：去掉 wiki 分类/后缀噪音（如 PRTS "XX（干员）"）
_CLEAN_RE = [
    (r"（干员）$", ""),
    (r"\(Operator\)$", ""),
]


def _clean_name(raw: str) -> str:
    name = raw.strip()
    for pat, rep in _CLEAN_RE:
        name = __import__("re").sub(pat, rep, name)
    return name


def prewarm(game_id: str, limit: int = 300, dry_run: bool = False) -> dict:
    game = registry.get_game(game_id)
    if not game.enabled or not game.wiki_base_url:
        return {"game": game_id, "skipped": True, "reason": "游戏未启用或无 wiki"}

    # 已有实体集合（静态 + 动态缓存），避免重复生成
    existed: set[str] = set()
    for t in FILE_BY_TYPE:
        for e in load_entries(game.data_dir, t):
            n = str(e.get("name") or "").strip()
            if n:
                existed.add(n)

    wiki = _Lazy.get_wiki(game.wiki_base_url)
    query = GAME_QUERIES.get(game_id, {}).get("character")
    if not query:
        return {"game": game_id, "skipped": True, "reason": "无清单查询"}

    results = wiki.ask(query, limit=limit)
    found = 0
    new = 0
    missing: list[str] = []
    for r in results:
        name = _clean_name(r.get("fulltext") or r.get("fullurl") or "")
        if not name or name.startswith("分类"):
            continue
        found += 1
        if name in existed:
            continue
        missing.append(name)
        if dry_run:
            continue
        entry, meta = generate_with_verification("character", name, game)
        if entry:
            new += 1
            existed.add(name)

    return {
        "game": game_id,
        "wiki_list": found,
        "already_have": found - len(missing) if not dry_run else found - len(missing),
        "new_entities": new,
        "dry_run": dry_run,
        "sample": missing[:10],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="官方 wiki 实体预热")
    parser.add_argument("game", choices=["genshin", "arknights"], nargs="?", default=None)
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true", help="只列出待补充实体，不实际生成")
    args = parser.parse_args()

    targets = [args.game] if args.game else list(GAME_QUERIES.keys())
    for g in targets:
        try:
            print(f"[{g}] {prewarm(g, args.limit, args.dry_run)}")
        except Exception as e:  # noqa: BLE001
            print(f"[{g}] 预热失败: {e}")


if __name__ == "__main__":
    main()
