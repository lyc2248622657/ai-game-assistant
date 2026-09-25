"""策略类工具：配队分析 / 材料换算 / 攻略检索（含视频跳转）

- analyze_teams(game, name)     配队分析：库内 teams 匹配优先，无匹配按职业规则/LLM 参考推荐
- calculate_materials(game, name, target)  材料总需求统计：明日方舟精1/精2+技能升级材料汇总
- search_guides(game, name, topic)  攻略检索：B站视频列表（标题/BV/UP）+ 搜索直达链接 + wiki 攻略页

B站搜索：带 UA/Referer 直连 search/type API（实测本地可用，无需登录签名）；
API 失败自动降级为"搜索直达链接"（构造 search.bilibili.com URL，用户点击跳转）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx

from app.core.logging import get_logger
from app.knowledge.games import Game, registry
from app.tools.base import Tool, ToolContext

logger = get_logger(__name__)

BACKEND = Path(__file__).resolve().parent.parent.parent

_BILI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
}
_BILI_SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"
_BILI_SEARCH_PAGE = "https://search.bilibili.com/all"

_EM_TAG = re.compile(r"</?em[^>]*>")
_HTML_ENT = re.compile(r"&[a-z]+;|\&#?\d+;")


def _clean_title(raw: str) -> str:
    t = _EM_TAG.sub("", raw or "")
    t = _HTML_ENT.sub("", t)
    return t.strip()


def _resolve_game(ctx: ToolContext, args: dict) -> Game:
    gid = str(args.get("game") or "").strip().lower()
    if gid in ("genshin", "arknights"):
        try:
            return registry.get_game(gid)
        except Exception:  # noqa: BLE001
            pass
    return ctx.game


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else [data]
    except Exception:  # noqa: BLE001
        return []


def _fetch_entity(game: Game, name: str) -> dict:
    """复用实体工具获取实体（静态库/动态缓存/wiki 全链路）"""
    from app.tools.game_entity import QueryGameEntityTool

    res = QueryGameEntityTool().run({"game": game.game_id, "type": "character", "name": name},
                                    ToolContext(game))
    if isinstance(res, dict) and res.get("found") and res.get("entity"):
        return res["entity"]
    return {}


def _count_to_num(raw) -> int:
    """'3w'/'3万' → 30000；纯数字原样"""
    s = str(raw or "").strip().lower().replace("，", "")
    if not s:
        return 0
    if s.endswith("w") or s.endswith("万"):
        try:
            return int(float(s[:-1]) * 10000)
        except Exception:  # noqa: BLE001
            return 0
    try:
        return int(float(s))
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------------------
# 工具 1：配队分析
# ---------------------------------------------------------------------------
class AnalyzeTeamsTool(Tool):
    name = "analyze_teams"
    description = (
        "分析指定角色/干员的推荐配队（原神/明日方舟）。用户问「XX适合什么队伍/怎么配队/配队推荐」时调用，"
        "传游戏与实体名；返回配队方案（库内配队优先，无匹配时按官方职业/特性规则推荐，LLM 仅作参考补充）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "game": {"type": "string", "enum": ["genshin", "arknights"],
                     "description": "游戏标识：原神=genshin，明日方舟=arknights"},
            "name": {"type": "string", "description": "角色/干员名称"},
        },
        "required": ["game", "name"],
    }

    # 明日方舟职业 → 通用编队逻辑（规则推荐，不编造干员名）
    AK_ROLE_TIPS = {
        "重装": "重装负责阻挡与承伤，编队通常 1-2 重装 + 先锋回费 + 狙击/术师输出 + 医疗保障",
        "近卫": "近卫是主力输出/切后排，编队围绕其输出轴配先锋回费与医疗保障",
        "先锋": "先锋负责前期回费，编队核心是尽快展开防线",
        "狙击": "狙击对空与远程输出，编队需重装承伤 + 医疗保障",
        "医疗": "医疗保障团队存活，编队需至少一名输出核心",
        "术师": "术师提供法术伤害，编队注意法术抗性高的敌人需物理补充",
        "辅助": "辅助提供减速/增伤/召唤，编队通常配合强输出核心",
        "特种": "特种提供推拉/快速复活等机制，编队灵活度高",
    }

    def run(self, args: dict, ctx: ToolContext) -> Any:
        game = _resolve_game(ctx, args)
        name = str(args.get("name") or "").strip()
        if not name:
            return {"error": "缺少 name"}
        entity = _fetch_entity(game, name)
        if not entity:
            return {"found": False, "error": f"未收录「{name}」的实体资料，无法分析配队"}

        teams: list[dict] = []
        source = "库内配队数据"

        # ① 库内 teams 匹配（原神 teams.json；明日方舟按官方职业规则）
        if game.game_id == "genshin":
            for t in _load_json(game.data_dir / "teams.json"):
                members = t.get("members") or []
                if name in members:
                    teams.append({"name": t.get("name"), "members": members, "core": t.get("core", "")})
            if not teams:
                source = "官方职业规则推荐"
                role = str(entity.get("role") or entity.get("element") or "")
                teams = [{
                    "name": f"{name}·{role} 通用队",
                    "members": [name],
                    "core": f"以{name}为核心，按元素（{entity.get('element','')}）与定位（{entity.get('role','')}）搭配",
                }]
        else:
            # 明日方舟：按官方职业/分支规则推荐（不编造干员名）
            source = "官方职业/分支规则推荐"
            role = str(entity.get("role") or "")
            weapon = str(entity.get("weapon_type") or "")
            tip = self.AK_ROLE_TIPS.get(role, "")
            teams = [{
                "name": f"{role}干员通用编队思路",
                "members": [name],
                "core": f"{tip}；{name}的职业分支为「{weapon}」，编队优先满足其机制需求（详见实体资料特性）",
            }]

        # ② LLM 参考补充（可选：库内/规则已覆盖时跳过，避免编造）
        llm_teams: list[dict] = []
        if not teams:
            try:
                from scripts.generator.llm import LLMClient
                from app.tools.game_entity import _Lazy

                llm = _Lazy.get_llm("")
                prompt = (
                    f"基于以下官方资料，为《{game.name}》的「{name}」推荐 2 套配队（标注为参考）：\n"
                    f"{json.dumps({k: entity.get(k) for k in ('role', 'weapon_type', 'element', 'characteristic', 'tags') if entity.get(k)}, ensure_ascii=False)}\n"
                    '输出 JSON：{"teams": [{"name": "队名", "members": ["成员"], "core": "核心机制一句话"}]}'
                    "（成员必须是该游戏真实存在的角色/干员；不确定就只写推荐思路不写具体成员）"
                )
                data = llm.chat_json("你是资深玩家，只推荐真实存在的角色。只输出 JSON。", prompt, temperature=0.3)
                for t in (data.get("teams") or [])[:2]:
                    if t.get("members"):
                        llm_teams.append(t)
                if llm_teams:
                    source += " + LLM 参考补充"
            except Exception as e:  # noqa: BLE001
                logger.warning("配队 LLM 补充失败: %s", e)
        teams = teams or llm_teams
        return {"found": True, "name": name, "teams": teams, "source": source}


# ---------------------------------------------------------------------------
# 工具 2：材料换算
# ---------------------------------------------------------------------------
class CalculateMaterialsTool(Tool):
    name = "calculate_materials"
    description = (
        "统计角色/干员的养成材料总需求（明日方舟：精英化精1/精2 + 技能升级材料汇总；原神：已收录养成数据汇总）。"
        "用户问「XX精英化材料总需求/精二要多少/养成材料统计」时调用，传游戏与实体名；返回按材料聚合的数量统计。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "game": {"type": "string", "enum": ["genshin", "arknights"],
                     "description": "游戏标识：原神=genshin，明日方舟=arknights"},
            "name": {"type": "string", "description": "角色/干员名称"},
            "target": {"type": "string",
                       "description": "统计范围：精英化/技能/全部（可空=全部）"},
        },
        "required": ["game", "name"],
    }

    def run(self, args: dict, ctx: ToolContext) -> Any:
        game = _resolve_game(ctx, args)
        name = str(args.get("name") or "").strip()
        target = str(args.get("target") or "全部").strip()
        if not name:
            return {"error": "缺少 name"}
        entity = _fetch_entity(game, name)
        if not entity:
            return {"found": False, "error": f"未收录「{name}」的实体资料，无法统计材料"}

        materials = entity.get("materials") or {}
        if not materials and game.game_id == "arknights":
            return {"found": False, "name": name,
                    "error": "该干员的材料数据未收录（官方 wiki 该字段缺失），可尝试查看攻略视频获取",
                    "guides": _guide_links(game, name, "养成材料")}

        # 聚合：{material: count}
        agg: dict[str, int] = {}
        sections: list[dict] = []
        if game.game_id == "arknights":
            want_elite = target in ("精英化", "全部")
            want_skill = target in ("技能", "全部")
            if want_elite:
                for e in materials.get("elite", []):
                    for it in e.get("items", []):
                        agg[it["material"]] = agg.get(it["material"], 0) + _count_to_num(it["count"])
                sections.append({"section": "精英化（精1+精2）", "count": len(materials.get("elite", []))})
            if want_skill:
                for s in materials.get("skill", []):
                    for it in s.get("items", []):
                        agg[it["material"]] = agg.get(it["material"], 0) + _count_to_num(it["count"])
                sections.append({"section": f"技能升级（技能{s.get('skill_index','')} Lv{s.get('level','')}）", "count": len(materials.get("skill", []))})
        else:
            # 原神：已收录数据有限，如实说明
            return {"found": True, "name": name,
                    "summary": "原神养成材料当前以攻略为准（数据管道未覆盖原神养成材料表）",
                    "items": [],
                    "guides": _guide_links(game, name, "养成材料")}

        items = sorted(agg.items(), key=lambda kv: -kv[1])
        total_extra = agg.get("龙门币", 0)
        return {
            "found": True,
            "name": name,
            "target": target,
            "summary": f"共 {len(items)} 种材料，合计龙门币约 {total_extra:,}（{total_extra // 10000}万）" if total_extra else "无龙门币消耗",
            "items": [{"material": m, "count": c} for m, c in items],
            "sections": sections,
        }


# ---------------------------------------------------------------------------
# 工具 3：攻略检索 + 视频跳转
# ---------------------------------------------------------------------------
def _guide_links(game: Game, name: str, topic: str) -> dict:
    """构造攻略资源链接（B站搜索直达 + wiki 攻略页）"""
    kw = f"{game.name} {name} {topic}"
    return {
        "bilibili_search": f"{_BILI_SEARCH_PAGE}?keyword={__import__('urllib.parse', fromlist=['quote']).quote(kw)}",
        "wiki_url": f"{game.wiki_base_url}?title=Special:搜索&search={__import__('urllib.parse', fromlist=['quote']).quote(name)}",
    }


class SearchGuidesTool(Tool):
    name = "search_guides"
    description = (
        "检索角色/干员的攻略视频与攻略链接（B站视频列表：标题/作者/链接；另有 B站搜索直达与 wiki 攻略页）。"
        "用户问「XX怎么玩/攻略/视频/打法/教程」时调用，传游戏与实体名（topic 可指定配队/养成/机制等）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "game": {"type": "string", "enum": ["genshin", "arknights"],
                     "description": "游戏标识：原神=genshin，明日方舟=arknights"},
            "name": {"type": "string", "description": "角色/干员名称"},
            "topic": {"type": "string", "description": "攻略主题（配队/养成/机制/玩法，可空）"},
        },
        "required": ["game", "name"],
    }

    def run(self, args: dict, ctx: ToolContext) -> Any:
        game = _resolve_game(ctx, args)
        name = str(args.get("name") or "").strip()
        topic = str(args.get("topic") or "攻略").strip()
        if not name:
            return {"error": "缺少 name"}
        keyword = f"{game.name} {name} {topic}"
        videos: list[dict] = []
        api_ok = False
        try:
            with httpx.Client(headers=_BILI_HEADERS, timeout=12, follow_redirects=True) as c:
                r = c.get(_BILI_SEARCH_URL, params={"search_type": "video", "keyword": keyword, "page": 1})
                r.raise_for_status()
                data = r.json()
                results = (data.get("data") or {}).get("result") or []
                if data.get("code") == 0:
                    api_ok = True
                    for v in results[:5]:
                        bvid = v.get("bvid")
                        if not bvid:
                            continue
                        videos.append({
                            "title": _clean_title(v.get("title", "")),
                            "url": f"https://www.bilibili.com/video/{bvid}",
                            "author": v.get("author", ""),
                            "duration": v.get("duration", ""),
                            "play": v.get("play", 0),
                        })
        except Exception as e:  # noqa: BLE001
            logger.warning("B站视频检索失败（降级搜索直达链接）: %s", e)

        links = _guide_links(game, name, topic)
        return {
            "found": True,
            "name": name,
            "topic": topic,
            "api_ok": api_ok,
            "videos": videos,
            "search_url": links["bilibili_search"],
            "wiki_url": links["wiki_url"],
            "note": "视频来自 B站搜索结果，点击直达；攻略内容以官方 wiki 为准" if api_ok else "视频检索接口暂不可用，已提供 B站搜索直达链接",
        }


# ---------------------------------------------------------------------------
# 工具 4：明日方舟关卡攻略检索（理解攻略类型：摆完挂机/单核/高配/低配/肉鸽N15）
# ---------------------------------------------------------------------------
_STAGE_RE = re.compile(r"\b([A-Za-z]{1,3}\d{1,2}(?:-\d{1,2})?|\d{1,2}-\d{1,2})\b")
_ROGUE_NAMES = ("傀影", "水月", "萨米", "萨卡兹", "肉鸽")

# 攻略类型黑话 → 搜索关键词（顺序敏感：先匹配长词再匹配短词）
_GUIDE_TYPE_RULES = [
    (("摆完挂机", "挂机"), "摆完挂机"),
    (("单核",), "单核"),
    (("双核",), "双核"),
    (("三核",), "三核"),
    (("高配",), "高配"),
    (("低配", "平民", "无六星", "少人"), "低配"),
]


def _normalize_stage(raw: str) -> str:
    """关卡名归一：'第八章 H8-4' → 'H8-4'；'傀影肉鸽N15' → '傀影肉鸽N15'"""
    s = str(raw or "").strip()
    m = _STAGE_RE.search(s)
    if m:
        return m.group(1).upper()
    # 肉鸽：保留 主题名 + N 数字
    n = re.search(r"N\s*(\d{1,2})", s, re.I)
    for rn in _ROGUE_NAMES:
        if rn in s:
            return f"{s} N{n.group(1)}" if n else s
    return s


def _parse_guide_type(user_text: str) -> str:
    """从用户问题提取攻略类型（默认空=通用攻略）"""
    s = str(user_text or "")
    n = re.search(r"[Nn]\s*(\d{1,2})", s)
    if ("肉鸽" in s or "集成战略" in s) and n:
        return f"肉鸽N{n.group(1)}"
    for keys, label in _GUIDE_TYPE_RULES:
        if any(k in s for k in keys):
            return label
    if "突袭" in s or "磨难" in s:
        return "突袭"
    return ""


class SearchStageGuidesTool(Tool):
    name = "search_stage_guides"
    description = (
        "检索《明日方舟》关卡攻略视频（活动关/主线/肉鸽等），自动理解攻略类型（摆完挂机/单核/双核/高配/低配/肉鸽N15等）。"
        "用户问「XX关怎么打/过关攻略/摆完挂机/单核作业/高配/肉鸽N15怎么过」时调用，"
        "传关卡名（如 H8-4/TW-8/1-7/傀影肉鸽）与攻略类型；返回 B站视频列表 + 搜索直达 + PRTS 攻略页。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "game": {"type": "string", "enum": ["genshin", "arknights"],
                     "description": "游戏标识：明日方舟=arknights"},
            "stage": {"type": "string", "description": "关卡名，如 H8-4、TW-8、1-7、傀影肉鸽N15"},
            "guide_type": {"type": "string",
                           "description": "攻略类型：摆完挂机/单核/双核/高配/低配/肉鸽N15/突袭，可空=通用攻略"},
        },
        "required": ["game", "stage"],
    }

    def run(self, args: dict, ctx: ToolContext) -> Any:
        game = _resolve_game(ctx, args)
        stage = _normalize_stage(args.get("stage") or "")
        guide_type = _parse_guide_type(str(args.get("guide_type") or ""))
        if not stage:
            return {"error": "缺少 stage"}
        # 构造搜索关键词：明日方舟 关卡 类型 攻略
        parts = ["明日方舟", stage]
        if guide_type:
            parts.append(guide_type)
        parts.append("攻略")
        keyword = " ".join(parts)

        videos: list[dict] = []
        api_ok = False
        # B站接口偶发 412：重试一次（退避 1.2s）
        for attempt in range(2):
            try:
                with httpx.Client(headers=_BILI_HEADERS, timeout=12, follow_redirects=True) as c:
                    r = c.get(_BILI_SEARCH_URL, params={"search_type": "video", "keyword": keyword, "page": 1})
                    r.raise_for_status()
                    data = r.json()
                    results = (data.get("data") or {}).get("result") or []
                    if data.get("code") == 0:
                        api_ok = True
                        for v in results[:5]:
                            bvid = v.get("bvid")
                            if not bvid:
                                continue
                            videos.append({
                                "title": _clean_title(v.get("title", "")),
                                "url": f"https://www.bilibili.com/video/{bvid}",
                                "author": v.get("author", ""),
                                "duration": v.get("duration", ""),
                                "play": v.get("play", 0),
                            })
                        break
                break
            except Exception as e:  # noqa: BLE001
                logger.warning("B站关卡攻略检索第 %s 次失败（%s）", attempt + 1, e)
                if attempt == 0:
                    import time
                    time.sleep(1.2)

        links = _guide_links(game, f"{stage} {guide_type}" if guide_type else stage, "攻略")
        return {
            "found": True,
            "stage": stage,
            "guide_type": guide_type or "通用",
            "keyword": keyword,
            "api_ok": api_ok,
            "videos": videos,
            "search_url": links["bilibili_search"],
            "wiki_url": links["wiki_url"],
            "note": "关卡攻略来自 B站搜索结果（作业通常标注干员配置），具体机制以 PRTS 为准",
        }
