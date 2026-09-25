"""数据采集编排：BWIKI → 知识包 JSON + WebP 小图

用法：
    python scripts/crawler/run.py --game genshin                       # 全类型采集
    python scripts/crawler/run.py --game genshin --types character     # 仅角色
    python scripts/crawler/run.py --game genshin --limit 5 --no-images # 小规模试跑

采集结果覆盖 data/<game>/<type>.json（wiki 为准）；
手工增强（配队、原型关联等）放 <type>_manual.json，校验/入库时合并。
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.crawler.base import WikiClient, parse_template_fields  # noqa: E402
from scripts.crawler.image import save_game_image  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("crawler")

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT / "config" / "crawler.yaml"
RARITY_RE = re.compile(r"(\d+)")


def clean_value(v: str) -> str:
    return re.sub(r"\s+", " ", v or "").strip()


def parse_rarity(v: str) -> int:
    m = RARITY_RE.search(v or "")
    return int(m.group(1)) if m else 0


def to_date(v: str) -> str:
    """2021年03月02日 → 2021-03-02"""
    m = re.search(r"(\d{4})年(\d{2})月(\d{2})日", v or "")
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return clean_value(v)


def split_tags(v: str) -> list[str]:
    return [t.strip() for t in re.split(r"[、,，/]", v or "") if t.strip()]


def build_entry(entry_type: str, page_title: str, fields: dict, cfg_fields: dict, source: str) -> dict:
    """wiki 模板字段 → 数据模板条目"""
    fm = cfg_fields if isinstance(cfg_fields, dict) else {}
    f = lambda key: clean_value(fields.get(key, ""))  # noqa: E731

    entry: dict = {"id": f"{entry_type}_{page_title}", "type": entry_type, "name": page_title}
    # 顶层映射
    entry["title"] = f(fm.get("title", "")) if fm.get("title") else ""
    for out, wiki_key in fm.items():
        if out in ("details_map", "title", "name"):
            continue
        if wiki_key:
            entry[out] = f(wiki_key)
    # 类型字段清洗
    if entry_type == "character":
        entry["rarity"] = parse_rarity(entry.get("rarity", ""))
        entry["debut_date"] = to_date(entry.get("debut_date", ""))
        if "tags" in entry:
            entry["tags"] = split_tags(entry["tags"])
        role = infer_role(entry.get("tags", []))
        entry["role"] = role
    elif entry_type == "weapon":
        entry["rarity"] = parse_rarity(entry.get("rarity", ""))
        entry["sub_stat"] = ""
        entry["main_stat"] = ""
        entry["passive"] = f(fm.get("passive", ""))
        desc = f(fm.get("passive_desc", ""))
        if desc:
            entry["passive"] = (entry["passive"] + "：" + desc) if entry["passive"] else desc
        entry["source"] = entry.get("source", "")
    elif entry_type == "artifact":
        entry["rarity"] = parse_rarity(entry.get("rarity", "")) or 5
        entry["set_pieces"] = ["生之花", "死之羽", "时之沙", "空之杯", "理之冠"]
        entry["domain"] = ""
    elif entry_type == "food":
        entry["rarity"] = parse_rarity(entry.get("rarity", ""))
        raw_type = entry.get("food_type_raw", "")
        entry["food_type"] = "special" if "特殊" in raw_type else "prototype"
        entry["owner_character"] = ""
        entry["prototype_food"] = ""
        entry.pop("food_type_raw", None)
    elif entry_type == "material":
        entry["rarity"] = parse_rarity(entry.get("rarity", ""))
        entry["usage"] = entry.get("usage", "")

    # details
    details: dict = {}
    dm = fm.get("details_map", {})
    for out, wiki_key in dm.items():
        v = clean_value(fields.get(wiki_key, ""))
        if v:
            details[out] = v
    if entry_type == "character":
        for k in ("90生命上限", "90攻击力", "90防御力"):
            if fields.get(k):
                details[f"lv90_{'hp' if '生命' in k else 'atk' if '攻击' in k else 'def'}"] = int(clean_value(fields[k]))
    entry["details"] = details
    entry["image"] = ""
    entry["source"] = source
    return entry


def infer_role(tags: list[str]) -> str:
    """从 TAG 粗略推断定位（wiki 无 role 字段；可后续手工完善）"""
    if any("治疗" in t for t in tags):
        return "治疗"
    if any("护盾" in t or "抗打断" in t for t in tags) and not any("输出" in t for t in tags):
        return "辅助"
    if any("暴击" in t or "元素爆发" in t or "输出" in t for t in tags):
        return "主C"
    return "待完善"


def _select_file(files: list[str], keywords: list[str], skip: list[str]) -> str | None:
    cleaned = [f for f in files if not any(s in f for s in skip)]
    if not cleaned:
        return None
    for kw in keywords:
        for f in cleaned:
            if kw in f:
                return f
    return cleaned[0]


def collect_special_food_links(client: WikiClient, cfg: dict) -> list[tuple[str, str, str]]:
    """全量特殊料理映射：ask 查询 角色→特殊料理，返回 [(角色, 原型料理, 特殊料理)]"""
    rows: list[tuple[str, str, str]] = []
    items = client.ask("[[分类:角色]]|?特殊料理", limit=50)
    for it in items:
        char = it["fulltext"]
        for spec in it.get("printouts", {}).get("特殊料理", []) or []:
            if spec:
                rows.append((char, "", spec))
    logger.info("特殊料理映射：%d 行（原型料理待后续增强）", len(rows))
    return rows


def collect_type(
    client: WikiClient,
    entry_type: str,
    cat_query: str,
    cfg: dict,
    game_dir: Path,
    limit: int | None,
    fetch_images: bool,
    workers: int,
) -> list[dict]:
    logger.info("[%s] ask 分类: %s", entry_type, cat_query)
    items = client.ask(cat_query, limit=50)
    if limit:
        items = items[:limit]
    logger.info("[%s] 条目 %d 个", entry_type, len(items))

    fields_cfg = cfg["fields"][entry_type]
    image_rules = cfg["image"]
    skip_kw = image_rules.get("skip_keywords", [])
    keywords = image_rules.get(entry_type, [])
    source = f"原神BWIKI（{cfg['base_url']}）"

    def process(item: dict) -> dict | None:
        title = item["fulltext"]
        try:
            wt = client.parse_wikitext(title)
            fields = parse_template_fields(wt)
            if not fields:
                logger.warning("[%s] %s 无模板字段，跳过", entry_type, title)
                return None
            entry = build_entry(entry_type, title, fields, fields_cfg, source)
            if fetch_images:
                files = client.page_images(title)
                chosen = _select_file(files, keywords, skip_kw)
                if chosen:
                    url = client.image_url(chosen)
                    if url:
                        img = save_game_image(client.client, url, game_dir, entry_type, title)
                        entry["image"] = img["path"]
            return entry
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] %s 采集失败: %s", entry_type, title, e)
            return None

    entries: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(process, item) for item in items]
        for fut in as_completed(futs):
            r = fut.result()
            if r:
                entries.append(r)
    entries.sort(key=lambda e: e["name"])
    return entries


def backfill_foods(foods: list[dict], links: list[tuple[str, str, str]]) -> int:
    """按特殊料理表回填 owner_character / prototype_food"""
    by_name = {f["name"]: f for f in foods}
    n = 0
    for char, proto, spec in links:
        food = by_name.get(spec)
        if not food:
            continue
        if proto and not food.get("prototype_food"):
            food["prototype_food"] = f"food_{proto}"
        if not food.get("owner_character"):
            food["owner_character"] = f"character_{char}"
        n += 1
    return n


def save(entries: list[dict], game_dir: Path, entry_type: str):
    path = game_dir / f"{entry_type}s.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=2)
    logger.info("已写入 %s: %d 条", path.name, len(entries))


def main():
    parser = argparse.ArgumentParser(description="数据采集管道")
    parser.add_argument("--game", required=True)
    parser.add_argument("--types", default="character,weapon,artifact,food,material", help="逗号分隔类型")
    parser.add_argument("--limit", type=int, default=None, help="每类限制条数（试跑）")
    parser.add_argument("--no-images", action="store_true", help="跳过图片下载")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()

    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))[args.game]
    game_dir = ROOT / "data" / args.game
    game_dir.mkdir(parents=True, exist_ok=True)

    client = WikiClient(cfg["base_url"])
    types = [t.strip() for t in args.types.split(",") if t.strip()]
    counts: dict[str, int] = {}
    t0 = time.time()

    try:
        for entry_type in types:
            cat = cfg["categories"].get(entry_type)
            if not cat:
                logger.warning("未配置分类: %s", entry_type)
                continue
            entries = collect_type(
                client, entry_type, cat, cfg, game_dir,
                args.limit, not args.no_images, args.workers,
            )
            save(entries, game_dir, entry_type)
            counts[entry_type] = len(entries)
            time.sleep(2)  # 类型切换间隔，降低限流风险

        # 特殊料理关联回填（角色/食物同时采集时）
        if "food" in counts and not args.limit:
            links = collect_special_food_links(client, cfg)
            foods = json.loads((game_dir / "foods.json").read_text(encoding="utf-8"))
            n = backfill_foods(foods, links)
            save(foods, game_dir, "food")
            counts["food_links"] = n

        # meta
        meta = {
            "source": cfg["base_url"],
            "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": "全量重跑即更新；图片为 WebP 压缩小图",
            "counts": counts,
            "duration_sec": round(time.time() - t0, 1),
        }
        (game_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("完成: %s 总耗时 %.1fs, 各类型 %s", args.game, meta["duration_sec"], counts)
    finally:
        client.close()


if __name__ == "__main__":
    main()
