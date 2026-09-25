# -*- coding: utf-8 -*-
"""数据生成编排：Planner → Generator → Validator →(回炉) → 落盘 → 图片关联

用 LangGraph 状态图表达「单批生成-校验-回炉」循环，批间由外层驱动；
与对话 Agent 共用 LangGraph 框架，是完整的 Generator-Critic 双 Agent 数据管道。

用法：
    python scripts/generator/run.py --game genshin              # 全部类型
    python scripts/generator/run.py --game genshin --types food # 仅料理
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from langgraph.graph import END, START, StateGraph  # noqa: E402

from scripts.generator.generator import Generator  # noqa: E402
from scripts.generator.llm import LLMClient  # noqa: E402
from scripts.generator.schema import BATCH_SIZE, TARGET_COUNTS, TYPE_SCHEMA  # noqa: E402
from scripts.generator.validator import Validator  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gen")

ROOT = Path(__file__).resolve().parent.parent.parent

# 生成时必须覆盖的角色（保证手工 teams.json 引用有效）
MUST_COVER = [
    "胡桃", "行秋", "钟离", "夜兰", "雷电将军", "香菱", "班尼特",
    "神里绫华", "枫原万叶", "珊瑚宫心海", "甘雨", "那维莱特", "芙宁娜",
    "纳西妲", "久岐忍", "达达利亚", "魈", "温迪", "艾尔海森",
]

MAX_RETRY = 3


class GenState(TypedDict):
    entry_type: str
    seed_names: list[str]
    ref_map: dict
    known_ids: set[str]
    batch: list[str]
    entries: list[dict]
    errors: list[str]
    retry: int
    feedback: str


def build_graph(generator: Generator, validator: Validator) -> StateGraph:
    def node_generate(state: GenState) -> dict:
        entries = generator.generate_batch(
            state["entry_type"],
            TYPE_SCHEMA[state["entry_type"]]["desc"],
            state["batch"],
            state.get("ref_map"),
            state.get("feedback") or None,
        )
        return {"entries": entries, "retry": state["retry"] + 1}

    def node_validate(state: GenState) -> dict:
        errors = validator.validate(
            state["entry_type"],
            state["entries"],
            state["batch"],
            state["known_ids"],
        )
        feedback = "\n".join(errors) if errors else ""
        return {"errors": errors, "feedback": feedback}

    def route(state: GenState) -> str:
        if state["errors"] and state["retry"] < MAX_RETRY:
            return "regenerate"
        return "accept"

    g = StateGraph(GenState)
    g.add_node("generate", node_generate)
    g.add_node("validate", node_validate)
    g.add_edge(START, "generate")
    g.add_edge("generate", "validate")
    g.add_conditional_edges("validate", route, {"regenerate": "generate", "accept": END})
    return g.compile()


def planner_names(llm: LLMClient, entry_type: str, count: int, extra: list[str] | None = None) -> list[str]:
    """Planner：LLM 生成条目名称清单（角色名/武器名等），并强制合并 MUST_COVER"""
    prompt = (
        f"列出《原神》中 {count} 个最有代表性、最知名、常被玩家讨论的{entry_type}条目名称"
        f"（{TYPE_SCHEMA[entry_type]['desc']}）。"
        f"只输出 JSON：{{\"names\": [\"名称\", ...]}}，不要解释。"
    )
    data = llm.chat_json("你是原神资深玩家。只输出 JSON。", prompt, temperature=0.3)
    names = [str(x).strip() for x in data.get("names") or [] if str(x).strip()]
    # 合并必含清单（去重保序）
    for name in extra or []:
        if name not in names:
            names.append(name)
    if len(names) > count + 8:
        names = names[: count + 8]
    return names


def image_lookup(game_dir: Path) -> dict[str, str]:
    """扫描已下载图片：{条目名: 相对路径}（images/character/胡桃.webp → 胡桃）"""
    lookup: dict[str, str] = {}
    img_root = game_dir / "images"
    if not img_root.exists():
        return lookup
    for f in sorted(img_root.rglob("*.webp")):
        rel = str(f.relative_to(game_dir)).replace("\\", "/")
        lookup[f.stem] = rel
    return lookup


def attach_images(entries: list[dict], lookup: dict[str, str]) -> int:
    n = 0
    for e in entries:
        if not e.get("image") and e.get("name") in lookup:
            e["image"] = lookup[e["name"]]
            n += 1
    return n


def run_type(
    llm: LLMClient,
    generator: Generator,
    validator: Validator,
    graph,
    entry_type: str,
    game_dir: Path,
    known_ids: set[str],
    images: dict[str, str],
    target: int,
) -> tuple[list[dict], dict]:
    """生成单个类型，返回 (entries, stats)"""
    logger.info("========== 开始生成 %s（目标 %d 条）==========", entry_type, target)
    t0 = time.time()

    # Planner
    extra = MUST_COVER if entry_type == "character" else None
    seed_names = planner_names(llm, entry_type, target, extra)
    logger.info("[planner:%s] 生成种子名称 %d 个", entry_type, len(seed_names))

    # 引用表：角色生成后，food/weapon/artifact 可引用角色 id
    ref_map = None
    if entry_type in ("food", "weapon", "artifact"):
        ref_map = {"角色": [f"character_{n}" for n in (images and list(images) or [])]}
        ref_map["角色"].extend(
            [f"character_{n}" for n in seed_names if n not in (images or {})]
        )
        ref_map["角色"] = list(dict.fromkeys(ref_map["角色"]))

    all_entries: list[dict] = []
    stats = {"planner_names": len(seed_names), "batches": 0, "regenerations": 0, "images": 0}
    retries_total = 0

    # 分批
    for i in range(0, len(seed_names), BATCH_SIZE):
        batch = seed_names[i : i + BATCH_SIZE]
        result = graph.invoke(
            {
                "entry_type": entry_type,
                "seed_names": batch,
                "ref_map": ref_map,
                "known_ids": set(known_ids),
                "batch": batch,
                "entries": [],
                "errors": [],
                "retry": 0,
                "feedback": "",
            }
        )
        batch_entries = result["entries"]
        retries_total += max(0, result["retry"] - 1)
        if not batch_entries:
            logger.warning("[batch %d] 生成失败/校验未通过，跳过", i // BATCH_SIZE + 1)
            continue
        all_entries.extend(batch_entries)
        stats["batches"] += 1
        logger.info("[batch %d] 通过 %d 条", i // BATCH_SIZE + 1, len(batch_entries))

    stats["regenerations"] = retries_total

    # 图片关联
    if entry_type == "character":
        stats["images"] = attach_images(all_entries, images)

    # 去重（同批可能重复名称）
    seen: set[str] = set()
    dedup: list[dict] = []
    for e in all_entries:
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        dedup.append(e)

    stats["count"] = len(dedup)
    stats["duration_sec"] = round(time.time() - t0, 1)
    logger.info("[%s] 完成：%d 条，耗时 %.1fs，回炉 %d 次", entry_type, len(dedup), stats["duration_sec"], retries_total)
    return dedup, stats


FILE_BY_TYPE = {
    "character": "characters.json",
    "weapon": "weapons.json",
    "artifact": "artifacts.json",
    "material": "materials.json",
    "food": "foods.json",
}


def main():
    import argparse

    parser = argparse.ArgumentParser(description="LLM 数据生成管道（Generator-Critic）")
    parser.add_argument("--game", default="genshin")
    parser.add_argument("--types", default="character,food,weapon,artifact,material")
    parser.add_argument("--llm-review", action="store_true", help="启用 LLM 事实抽审")
    args = parser.parse_args()

    game_dir = ROOT / "data" / args.game
    game_dir.mkdir(parents=True, exist_ok=True)

    llm = LLMClient()
    generator = Generator(llm)
    validator = Validator(llm, use_llm_review=args.llm_review)
    graph = build_graph(generator, validator)

    types = [t.strip() for t in args.types.split(",") if t.strip()]
    known_ids: set[str] = set()
    # 已存在的 id 加入已知集（保证 team 引用校验等）
    for f in game_dir.glob("*.json"):
        if f.name == "TEMPLATE.md":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else [data]
            known_ids.update(e.get("id") for e in items if isinstance(e, dict))
        except Exception:  # noqa: BLE001
            pass

    images = image_lookup(game_dir)
    logger.info("已发现本地图片 %d 张", len(images))

    meta: dict = {"source": "DeepSeek LLM 生成（Generator-Critic 双 Agent）", "stats": {}}
    all_stats = meta["stats"]

    try:
        for entry_type in types:
            if entry_type not in TARGET_COUNTS:
                logger.warning("未知类型: %s", entry_type)
                continue
            entries, stats = run_type(
                llm, generator, validator, graph, entry_type, game_dir,
                known_ids, images, TARGET_COUNTS[entry_type],
            )
            out = game_dir / FILE_BY_TYPE[entry_type]
            out.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
            all_stats[entry_type] = stats
            known_ids.update(e["id"] for e in entries)
            logger.info("已写入 %s：%d 条", out.name, len(entries))

        meta["collected_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        meta["cost"] = llm.cost_report()
        (game_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("全部完成。%s", llm.cost_report())
    finally:
        pass


if __name__ == "__main__":
    main()
