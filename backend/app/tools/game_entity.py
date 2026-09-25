"""按需游戏实体查询工具（核心 Agent 工具，多游戏）

支持游戏：原神（genshin）→ bilibili 原神 wiki；明日方舟（arknights）→ PRTS wiki。
Agent 通过 `game` 参数指定游戏（未传时用上下文绑定游戏兜底）。

三层获取：
  ① 静态知识库（data/<game>/*.json，人工核验）→ 命中直接返回
  ② 动态缓存库（data/<game>/dynamic/*.json，历史官方源/LLM 生成 + 交叉验证）
  ③ 未命中 → 【官方源为主要依据】先抓对应游戏 wiki（技能数值/命之座/生日/基础属性以官方为准），
            LLM 仅补充 wiki 缺失的推断字段（定位/主流配队/简介等）
            → 校验通过 → 写回动态缓存（增量知识库）

头像图片：问角色给角色图、问武器给武器图——从对应游戏 wiki 页面图获取直链
（优先"立绘/头像"命名，失败取首图），随实体返回 image_url 供前端渲染。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.knowledge.games import Game, registry
from app.tools.base import Tool, ToolContext

logger = get_logger(__name__)

BACKEND = Path(__file__).resolve().parent.parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts.crawler.base import WikiClient, parse_template_fields  # noqa: E402
from scripts.crawler.official_source import parse_character_official  # noqa: E402
from scripts.crawler.arknights_source import parse_operator_official  # noqa: E402
from scripts.generator.generator import Generator, normalize_entry  # noqa: E402
from scripts.generator.llm import LLMClient  # noqa: E402
from scripts.generator.validator import Validator  # noqa: E402

# 文件 → 类型（与 validate_data.py 对齐；按游戏数据目录实际文件动态扩展）
FILE_BY_TYPE = {
    "character": "characters.json",
    "weapon": "weapons.json",
    "artifact": "artifacts.json",
    "material": "materials.json",
    "food": "foods.json",
}

# 头像命名关键词（wiki 页面图优先匹配，其次取首图）
_IMAGE_KEYWORDS = ("立绘", "头像", "icon", "头像图片", "角色立绘")

# wiki 模板字段 → 标准字段（交叉验证映射；按游戏分层，wiki 值优先）
# 原神：bilibili 原神 wiki；明日方舟：PRTS wiki（稀有度 0-5 对应 1-6 星，需 +1）
VERIFY_MAP = {
    "genshin": {
        "character": {
            "title": "称号",
            "element": "元素属性",
            "weapon_type": "武器类型",
            "rarity": "稀有度",
            "region": "所属",
            "debut_version": "实装版本",
            "debut_date": "实装日期",
            "special_food": "特殊料理",
            "summary": "介绍",
            "birthday": "生日",
        },
        "weapon": {"category": "类型", "rarity": "稀有度", "passive": "技能介绍"},
        "food": {"rarity": "稀有度", "effect": "效果说明", "obtain": "获取方式"},
        "material": {"category": "类型", "rarity": "稀有度", "usage": "用途"},
        "artifact": {"rarity": "最高稀有度", "two_piece": "两件套效果", "four_piece": "四件套效果"},
    },
    "arknights": {
        "character": {
            "title": "干员外文名",
            "rarity": "稀有度",          # PRTS 0-5 → 1-6 星（+1）
            "region": "所属国家",
            "debut_date": "上线时间",
            "birthday": "生日",
            "role": "职业",              # 重装/先锋…
            "weapon_type": "分支",       # 本源铁卫/战术家…
            "summary": "介绍",
        },
    },
}

# 明日方舟 PRTS 额外解析字段（wikitext 模板名 → 标准字段）
ARKNIGHTS_EXTRA_FIELDS = {
    "特性": "characteristic",      # CharinfoV2 特性
    "标签": "tags_raw",            # CharinfoV2 标签
    "获得方式": "obtain",          # 干员获得方式
}

# 需要 +1 转换稀有度的游戏（PRTS 0-5 → 1-6 星）
RARITY_OFFSET = {"arknights": 1}

# 静态库检索用的字段名（character 的元素/武器等顶层字段）
TYPE_KEYS = {
    "character": ["element", "weapon_type", "region", "title", "rarity"],
    "weapon": ["category", "rarity", "sub_stat"],
    "artifact": ["two_piece", "four_piece", "rarity"],
    "food": ["food_type", "effect", "obtain", "rarity"],
    "material": ["category", "rarity", "usage"],
}


def _clean(v: str) -> str:
    return re.sub(r"\s+", " ", v or "").strip()


def _parse_rarity(v) -> int | None:
    m = re.search(r"(\d+)", str(v or ""))
    return int(m.group(1)) if m else None


class _Lazy:
    """懒加载单例：LLM 客户端 / Wiki 客户端（避免请求级重复创建）"""

    llm: LLMClient | None = None
    wiki: WikiClient | None = None

    @classmethod
    def get_llm(cls, base_url: str) -> LLMClient:
        if cls.llm is None:
            cls.llm = LLMClient()
        return cls.llm

    @classmethod
    def get_wiki(cls, base_url: str) -> WikiClient:
        if cls.wiki is None or cls.wiki.base_url != base_url:
            cls.wiki = WikiClient(base_url)
        return cls.wiki


def load_entries(game_dir: Path, entry_type: str) -> list[dict]:
    """读静态库 + 动态缓存库"""
    out: list[dict] = []
    fname = FILE_BY_TYPE.get(entry_type)
    if not fname:
        return out
    for sub in ("", "dynamic"):
        path = game_dir / sub / fname
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                items = data if isinstance(data, list) else [data]
                out.extend(e for e in items if isinstance(e, dict))
            except Exception:  # noqa: BLE001
                logger.warning("读取失败 %s", path)
    return out


def search_entry(entries: list[dict], name: str) -> dict | None:
    """精确名匹配，其次名称包含匹配"""
    for e in entries:
        if e.get("name") == name:
            return e
    for e in entries:
        if name in e.get("name", "") or e.get("name", "") in name:
            return e
    return None


def cross_validate(entry: dict, wiki_fields: dict, entry_type: str, game_id: str) -> list[str]:
    """wiki 交叉验证：关键字段以 wiki 为准修正，返回差异记录（按游戏取映射）"""
    diffs: list[str] = []
    mapping = VERIFY_MAP.get(game_id, {}).get(entry_type, {})
    offset = RARITY_OFFSET.get(game_id, 0)
    for field, wiki_key in mapping.items():
        wiki_val = _clean(wiki_fields.get(wiki_key, ""))
        if not wiki_val:
            continue
        if field == "rarity":
            wiki_n = _parse_rarity(wiki_val)
            llm_n = _parse_rarity(entry.get("rarity"))
            if wiki_n is not None:
                wiki_n += offset  # 明日方舟 PRTS 稀有度 0-5 → 1-6 星
            if wiki_n and llm_n and wiki_n != llm_n:
                diffs.append(f"{field}: LLM={llm_n} → wiki={wiki_n}（以 wiki 为准）")
                entry["rarity"] = wiki_n
            elif wiki_n and not llm_n:
                entry["rarity"] = wiki_n
            continue
        llm_val = entry.get(field)
        if llm_val and str(llm_val) != wiki_val:
            diffs.append(f"{field}: LLM={llm_val} → wiki={wiki_val}（以 wiki 为准）")
        entry[field] = wiki_val
    return diffs


def _fetch_official(entry_type: str, name: str, game: Game) -> dict:
    """抓官方 wiki 字段（wiki 为主要依据，按游戏路由：原神→bilibili、明日方舟→PRTS）。

    返回：基础模板字段（稀有度/生日/地区…）+ character 增强字段（原神：命座/技能+数值）。
    失败返回空 dict（调用方降级 LLM）。
    """
    wiki_base = game.wiki_base_url
    if not wiki_base:
        return {}
    try:
        wiki = _Lazy.get_wiki(wiki_base)
        real = wiki.resolve_title(name)  # P1-1：redirect/别名解析
        wt = wiki.parse_wikitext(real)
        wf = parse_template_fields(wt)
        if not wf:
            logger.warning("[%s] wiki 无模板字段（页面不存在或结构不同）", name)
            return {}
        # 注意：稀有度偏移（PRTS 0-5 → 1-6 星）统一在 _build_from_wiki / cross_validate 处理，
        # 此处保留 wiki 原始值，避免双重转换。
        if entry_type == "character":
            if game.game_id == "genshin":
                official = parse_character_official(wt, wiki.parse_rendered_html(name))
                return {**wf, **official}
            # 明日方舟：额外提取特性/标签/获得方式 + 技能数值表/天赋/精英化与技能升级材料
            for k, std in ARKNIGHTS_EXTRA_FIELDS.items():
                if wf.get(k) and std not in wf:
                    wf[std] = wf[k]
            return {**wf, **parse_operator_official(wt)}
        return wf
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] 官方 wiki 获取失败（降级 LLM 生成）: %s", name, e)
        return {}


def _llm_fill(llm: LLMClient, name: str, wiki_fields: dict, entry: dict, game_id: str) -> dict:
    """LLM 只补 wiki 缺失的推断字段（role/teams/tags/summary 等），按游戏定制。

    硬性约束：wiki 已提供的硬数据（稀有度/生日/技能/天赋等）禁止改动或编造。
    """
    if game_id == "arknights":
        known = {
            k: wiki_fields.get(k) or entry.get(k)
            for k in ("title", "rarity", "region", "birthday", "role", "weapon_type", "characteristic")
            if (wiki_fields.get(k) or entry.get(k))
        }
        prompt = (
            f"重要：这是《明日方舟》干员「{name}」（2026 年实装的六星本源铁卫，雷姆必拓出身），"
            f"绝不可能是《原神》角色，也不要猜测其属于其他游戏。\n"
            f"官方数据已从 PRTS wiki 获取（稀有度/职业/分支/生日/特性均以此为准，不得改动或编造）：\n"
            f"{json.dumps(known, ensure_ascii=False)}\n"
            "请只补充 wiki 未提供的以下推断字段并输出 JSON：\n"
            '{"element": "物理/法术/真实 之一（按干员普攻伤害类型）", '
            '"tags": ["标签", ...], '
            '"teams": [{"name": "配队名", "members": ["干员名", ...], "core": "核心机制一句话"}], '
            '"playstyle": "玩法要点一句话"}'
            "（不需要 summary——已由官方字段自动生成；如不熟悉该干员，基于上述官方字段客观描述即可，严禁编造'未实装/未知/属于其他游戏'等否定性内容）"
        )
        sys_prompt = "你是明日方舟资深玩家。官方数据已提供，只补充缺失字段，禁止编造稀有度/生日/技能/天赋/游戏归属。只输出 JSON。"
    else:
        known = {
            k: wiki_fields.get(k) or entry.get(k)
            for k in ("title", "element", "weapon_type", "rarity", "region", "birthday")
            if (wiki_fields.get(k) or entry.get(k))
        }
        prompt = (
            f"角色「{name}」的官方数据已从原神 wiki 获取（技能数值/命之座/生日/基础属性均以此为准，不得改动或编造）：\n"
            f"{json.dumps(known, ensure_ascii=False)}\n"
            "请只补充 wiki 未提供的以下推断字段并输出 JSON：\n"
            '{"role": "主C/副C/辅助/治疗/护盾辅助 之一", '
            '"teams": [{"name": "配队名", "members": ["角色名", ...], "core": "核心机制一句话"}], '
            '"special_food": "特殊料理名（无则空字符串）", '
            '"tags": ["标签", ...], '
            '"summary": "一句话简介（30字内）"}'
        )
        sys_prompt = "你是原神资深玩家。官方数据已提供，只补充缺失字段，禁止编造技能/命座/生日。只输出 JSON。"
    try:
        data = llm.chat_json(sys_prompt, prompt, temperature=0.3)
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] LLM 补缺失败: %s", name, e)
        return {}
    out: dict = {}
    # 明日方舟 summary 由官方字段拼装，LLM 不覆盖；原神保留 LLM summary
    allowed = ("role", "teams", "special_food", "tags", "summary", "element", "playstyle")
    if game_id == "arknights":
        allowed = ("role", "teams", "tags", "element", "playstyle")
    for k in allowed:
        if k in data and data[k] not in (None, ""):
            out[k] = data[k]
    return out


def _build_from_wiki(llm: LLMClient, entry_type: str, name: str, wiki_fields: dict, game_id: str) -> dict:
    """wiki 官方字段为主组装条目 + LLM 仅补缺失推断字段（按游戏路由）"""
    entry: dict = {"id": f"{entry_type}_{name}", "type": entry_type, "name": name, "image": ""}
    mapping = VERIFY_MAP.get(game_id, {}).get(entry_type, {})
    offset = RARITY_OFFSET.get(game_id, 0)
    for std, wkey in mapping.items():
        v = _clean(wiki_fields.get(wkey, ""))
        if not v:
            continue
        if std == "rarity":
            n = _parse_rarity(v)
            entry[std] = (n + offset) if n is not None else v
        else:
            entry[std] = v
    # 明日方舟额外字段（特性/标签/获得方式）
    if game_id == "arknights" and entry_type == "character":
        for std in ("characteristic", "tags_raw", "obtain"):
            if wiki_fields.get(std):
                entry[std] = wiki_fields[std]
        if entry.get("tags_raw"):
            entry["tags"] = [t.strip() for t in str(entry.pop("tags_raw")).replace("，", " ").replace("  ", " ").split(" ") if t.strip()]
        # summary 由官方字段拼装（不交给 LLM 编造，避免误判/幻觉）
        parts = []
        if entry.get("rarity"):
            parts.append(f"{entry['rarity']}星")
        if entry.get("role"):
            parts.append(entry["role"])
        if entry.get("weapon_type"):
            parts.append(f"·{entry['weapon_type']}")
        if entry.get("region"):
            parts.append(f"，出身{entry['region']}")
        if entry.get("characteristic"):
            parts.append(f"，{entry['characteristic']}")
        if len(parts) >= 2:
            entry["summary"] = "".join(parts)[:120]
    if entry_type == "character":
        for k in ("birthday", "constellations", "skills", "talents", "materials"):
            if k in wiki_fields and wiki_fields[k]:
                entry[k] = wiki_fields[k]
        # summary 优先 wiki 介绍精简，缺失再由 LLM 补
        intro = _clean(wiki_fields.get("介绍", "")) or _clean(wiki_fields.get("简介", ""))
        if intro:
            entry["summary"] = intro[:120]
    fills = _llm_fill(llm, name, wiki_fields, entry, game_id)
    for k, v in fills.items():
        if k not in entry or not entry[k]:
            entry[k] = v
    source_note = (
        "原神官方wiki（BWIKI）为主要依据 + DeepSeek 仅补缺失"
        if game_id == "genshin"
        else "PRTS官方wiki为主要依据 + DeepSeek 仅补缺失"
    )
    entry["source"] = source_note
    return entry


def _generate_verified(
    gen: Generator,
    entry_type: str,
    name: str,
    game: Game,
    feedback: str | None = None,
) -> tuple[dict | None, dict]:
    """生成一次 + wiki 交叉验证（成对执行，确保每次生成的条目都过验证）"""
    from scripts.generator.schema import TYPE_SCHEMA

    entries = gen.generate_batch(entry_type, TYPE_SCHEMA[entry_type]["desc"], [name], feedback=feedback)
    if not entries:
        return None, {"error": "LLM 生成失败"}
    entry = entries[0]
    meta: dict = {"source": "dynamic", "wiki_checked": False, "diffs": [], "errors": []}

    wiki_base = game.wiki_base_url
    if wiki_base:
        try:
            wiki = _Lazy.get_wiki(wiki_base)
            real = wiki.resolve_title(name)  # P1-1：redirect/别名解析
            wt = wiki.parse_wikitext(real)
            wf = parse_template_fields(wt)
            if wf:
                diffs = cross_validate(entry, wf, entry_type, game.game_id)
                meta["wiki_checked"] = True
                meta["diffs"] = diffs
                logger.info("[%s] wiki 交叉验证完成，修正 %d 处", name, len(diffs))
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] wiki 验证失败（保留 LLM 值）: %s", name, e)
            meta["diffs"].append(f"wiki 验证不可用: {e}")
    return entry, meta


def _enhance_entry_from_wiki(game: Game, entry_type: str, name: str, out: dict, meta: dict) -> None:
    """P0-1 增量补全：缓存命中但增强字段缺失（静态库旧数据/历史缓存）→
    尝试从官方 wiki 补全技能/天赋/材料（明日方舟）或命座/技能数值（原神）并写回。

    只补缺失字段，不覆盖已有值；wiki 获取失败静默跳过（不阻断回答）。
    """
    if entry_type != "character" or not game.wiki_base_url:
        return
    enhanced = {
        "arknights": ("skills", "talents", "materials"),
        "genshin": ("constellations", "skills"),
    }.get(game.game_id, ())
    missing = [k for k in enhanced if not out.get(k)]
    if not missing:
        return
    try:
        wf = _fetch_official(entry_type, name, game)
        if not wf:
            return
        changed = False
        for k in missing:
            v = wf.get(k)
            if v:
                out[k] = v
                changed = True
        if changed:
            _save_dynamic(game, entry_type, {**out, "_meta": {**meta, "source": "official_wiki_enhanced"}})
            logger.info("[%s] 命中缓存字段补全: %s", name, [k for k in missing if out.get(k)])
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] 字段补全失败（忽略）: %s", name, e)


def _collect_ref_ids(game: Game) -> set[str]:
    """收集库内全部 id/name 作为引用校验白名单"""
    ref_ids: set[str] = set()
    for t in FILE_BY_TYPE:
        for e in load_entries(game.data_dir, t):
            if e.get("id"):
                ref_ids.add(e["id"])
            if e.get("name"):
                ref_ids.add(e["name"])
    return ref_ids


def generate_with_verification(
    entry_type: str,
    name: str,
    game: Game,
) -> tuple[dict | None, dict]:
    """官方源为主要依据：先抓对应游戏 wiki（稀有度/生日/职业等以官方为准），
    LLM 仅补缺失推断字段 → 引用校验 → 写回动态缓存。

    - 官方源成功：数据来自 wiki 天然可信，不做 LLM 幻觉硬校验
      （Validator schema 为原神设计，明日方舟职业/分支/6星会被误判非法）；
      仅检查引用缺失（记录不阻断）。
    - 官方源失败：原神走「LLM 生成 + wiki 交叉验证」兜底；
      明日方舟不 LLM 兜底（防编造游戏归属/星座等原神式幻觉），如实返回未收录。
    """
    llm = _Lazy.get_llm("")
    gen = Generator(llm)
    val = Validator(llm)

    wiki_fields = _fetch_official(entry_type, name, game)
    if wiki_fields:
        entry = _build_from_wiki(llm, entry_type, name, wiki_fields, game.game_id)
        meta: dict = {"source": "official_wiki", "wiki_checked": True, "diffs": [], "errors": []}
        # 仅引用缺失检查（官方数据不跑幻觉硬校验）
        gaps = [x for x in val.validate(entry_type, [entry], [name], _collect_ref_ids(game))
                if "引用不存在" in x]
        if gaps:
            meta["reference_gaps"] = gaps
            logger.info("[%s] 引用缺失（已标注不阻断）: %s", name, gaps[:3])
    else:
        if game.game_id == "arknights":
            logger.warning("[%s] PRTS 获取失败，不 LLM 兜底（防编造）", name)
            return None, {"source": "wiki_failed", "wiki_checked": False, "diffs": [],
                          "errors": ["官方 wiki 获取失败，未收录该干员"]}
        entry, meta = _generate_verified(gen, entry_type, name, game)
        if not entry:
            return None, meta
        if not meta.get("errors") and not meta.get("reference_gaps"):
            pass  # 通过，继续
        # 硬错误存在时返回但不落库（见下）

    # 写回动态缓存（增量知识库）
    meta["source"] = "dynamic"
    entry["_meta"] = meta
    _save_dynamic(game, entry_type, entry)
    return entry, meta


def _save_dynamic(game: Game, entry_type: str, entry: dict):
    dyn_dir = game.data_dir / "dynamic"
    dyn_dir.mkdir(parents=True, exist_ok=True)
    path = dyn_dir / FILE_BY_TYPE[entry_type]
    items: list[dict] = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else [data]
        except Exception:  # noqa: BLE001
            items = []
    items = [e for e in items if e.get("id") != entry.get("id")]
    items.append(entry)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("[%s] 已写入动态缓存: %s", entry.get("name"), path)


def _attach_image(game: Game, entry_type: str, name: str, entry: dict) -> None:
    """从对应游戏 wiki 页面图获取实体头像直链（角色图/武器图）。

    优先"立绘/头像"命名的图片，失败取页面首图；无 wiki 或抓取失败静默跳过
    （不阻断回答，后续图形化功能按此字段渲染）。
    """
    if entry.get("image_url") or entry.get("image"):
        return
    wiki_base = game.wiki_base_url
    if not wiki_base:
        return
    try:
        wiki = _Lazy.get_wiki(wiki_base)
        real = wiki.resolve_title(name)  # P1-1：redirect/别名解析
        files = wiki.page_images(real)
        if not files:
            logger.info("[%s] wiki 页面无图片", name)
            return
        pick = next((f for f in files if any(k in f for k in _IMAGE_KEYWORDS)), files[0])
        url = wiki.image_url(pick)
        if url:
            entry["image_url"] = url
            if not entry.get("image"):
                entry["image"] = url
            logger.info("[%s] 头像图片: %s", name, url)
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] 图片获取失败（忽略）: %s", name, e)


def _resolve_game(ctx: ToolContext, args: dict) -> Game:
    """解析工具的目标游戏：优先 Agent 传入的 game 参数，其次上下文绑定游戏"""
    gid = str(args.get("game") or "").strip().lower()
    if gid in ("genshin", "arknights"):
        try:
            return registry.get_game(gid)
        except Exception:  # noqa: BLE001
            pass
    return ctx.game


class QueryGameEntityTool(Tool):
    """按需实体查询：静态库 → 动态缓存 → LLM 生成 + wiki 交叉验证（多游戏）"""

    name = "query_game_entity"
    description = (
        "查询指定游戏（原神/明日方舟）中指定实体的完整信息（角色/干员/武器/圣遗物/料理/材料）。"
        "用户问某个具体角色/物品时调用，传游戏、实体类型与名称；返回该实体专有的结构化信息与头像图片。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "game": {
                "type": "string",
                "enum": ["genshin", "arknights"],
                "description": "游戏标识：原神=genshin，明日方舟=arknights（必须与问题中实体所属游戏一致）",
            },
            "type": {
                "type": "string",
                "enum": ["character", "weapon", "artifact", "material", "food"],
                "description": "实体类型（明日方舟为 character=干员）",
            },
            "name": {"type": "string", "description": "实体名称（如 胡桃、银灰、天空之翼）"},
        },
        "required": ["game", "type", "name"],
    }

    def run(self, args: dict, ctx: ToolContext) -> Any:
        entry_type = args.get("type")
        name = args.get("name", "").strip()
        if not entry_type or not name:
            return {"error": "缺少 type 或 name"}

        game: Game = _resolve_game(ctx, args)
        game_dir = game.data_dir

        # ① 静态库 + 动态缓存检索
        entries = load_entries(game_dir, entry_type)
        hit = search_entry(entries, name)
        if hit:
            meta = hit.get("_meta") or {"source": "static"}
            out = {k: v for k, v in hit.items() if k != "_meta"}
            # 缓存条目缺图 → 尝试补抓头像并写回（不影响回答）
            if not out.get("image_url") and not out.get("image") and game.wiki_base_url:
                _attach_image(game, entry_type, name, out)
                if out.get("image_url") and hit.get("_meta"):
                    _save_dynamic(game, entry_type, {**hit, **out})
            # P0-1 增量补全：缓存命中但增强字段缺失（静态库旧数据/历史缓存）
            # → 尝试从官方 wiki 补全技能/天赋/材料并写回（不阻断回答）
            _enhance_entry_from_wiki(game, entry_type, name, out, meta)
            return {"found": True, "entity": out, "_meta": meta}

        # ② 未命中 → 按需生成 + 交叉验证（游戏关闭动态生成时直接返回未收录）
        if not game.dynamic_generation:
            return {"found": False, "error": "该实体资料暂未收录（该游戏未启用动态生成）"}
        entry, meta = generate_with_verification(entry_type, name, game)
        if not entry:
            return {"found": False, "error": "该实体未能获取，请确认名称或稍后再试"}
        _attach_image(game, entry_type, name, entry)
        if entry.get("image_url"):
            _save_dynamic(game, entry_type, entry)
        out = {k: v for k, v in entry.items() if k != "_meta"}
        return {"found": True, "entity": out, "_meta": meta, "note": "动态生成（LLM + wiki 交叉验证）"}
