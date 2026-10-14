"""养成规划工具：资源预算 × 跨源聚合 × 多步排期（业务约束改造 A→B）

业务目标：把"单跳知识问答"升级为带真实约束的多步决策——
  - 资源约束：用户当前原石/星琼预算有限，需回答"够不够抽、缺口多少、怎么攒"；
  - 跨源聚合：角色实体（backend/data/genshin/dynamic/characters.json）+ 卡池/活动日历
    （backend/data/events_cache.json）+ 通用养成常量（游戏公开规则）；
  - 写操作闭环：计划确认后由 save_build_plan 写入 SQLite（plans 表），会话内可回读。

口径说明：通用养成常量（升级/突破摩拉、经验书、元素宝石、天赋书数量）为游戏公开规则，
写成代码常量可复核；资源测算（每日委托/深渊/活动可攒原石）为估算口径，输出带 disclaimer。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.knowledge.games import Game, registry
from app.tools.base import Tool, ToolContext

logger = get_logger(__name__)

BACKEND = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BACKEND / "data"

# ---------------------------------------------------------------------------
# 通用养成常量（游戏公开规则；以代码常量形式留档，可复核）
# ---------------------------------------------------------------------------
ASCENSION_MORA = 2_093_000        # 角色 1→90：突破+升级摩拉（不含天赋/武器）
ASCENSION_EXP = 4_189_676         # 角色 1→90：总经验
ASCENSION_BOOKS = 419             # ≈ 大英雄的经验（紫书）本数
GEM_BY_ELEMENT = {
    "火": "燃愿玛瑙", "水": "涤净青金", "雷": "最胜紫晶", "冰": "哀叙冰玉",
    "风": "自在松石", "岩": "坚牢黄玉", "草": "生长碧翡",
}
GEM_COUNTS = {"碎屑": 1, "断片": 9, "块": 9, "全块": 6}   # 元素宝石（1→90 六次突破合计）
LOCAL_SPECIALTY_COUNT = 168        # 地区特产（0→90 累计）
BOSS_MATERIAL_COUNT = 46           # 首领突破材料（周常首领掉落）
COMMON_MATERIAL_COUNT = 18         # 怪物材料（突破所需）

# 天赋（单天赋 Lv1→目标）：(教导, 引导, 哲学) 与累计摩拉 —— 仅取常见目标 9/10 级
TALENT_BOOKS = {9: (9, 13, 22), 10: (9, 13, 38)}
TALENT_MORA = {9: 952_500, 10: 1_652_500}

# 原石测算（原神；估算口径）
WISH_PRICE = 160
PITY_SOFT = 14_400        # 小保底 90 抽 = 14400 原石
PITY_HARD = 28_800         # 大保底 180 抽 = 28800 原石
DAILY_PRIMOGEM = 60        # 每日委托
ABYSS_PRIMOGEM = 800       # 深境螺旋每期（可打满）
EVENT_PRIMOGEM_EST = 1_000  # 每活动估算（版本大活动更高，取保守值）

DISCLAIMER = "资源测算为通用规则估算，角色特有材料与最终数值以游戏内为准。"


def _load_json(path: Path) -> Any:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.warning("读取 %s 失败", path)
        return []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_left(end_iso: str) -> int:
    """活动/卡池剩余天数（按自然日，取整）。数据源为东八区本地时间（无时区），
    按 UTC+8 解释后与当前 UTC 比较。"""
    try:
        from datetime import timedelta
        end = datetime.fromisoformat(end_iso)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone(timedelta(hours=8)))
        return max(0, int((end - datetime.now(timezone.utc)).total_seconds() // 86400))
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------------------
# 计划存储（写操作闭环：SQLite plans 表）
# ---------------------------------------------------------------------------
class PlanStore:
    """养成计划持久化：按会话存取，状态可回读"""

    def __init__(self, db_path: str | None = None):
        self.db_path = Path(db_path or settings.sqlite_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    game_id TEXT NOT NULL,
                    character TEXT NOT NULL,
                    goal TEXT,
                    plan_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'planned',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_plans_session ON plans(session_id, id);
                """
            )

    def save(self, session_id: str, game_id: str, character: str, goal: str,
             plan: dict, status: str = "planned") -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO plans(session_id, game_id, character, goal, plan_json, status, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (session_id, game_id, character, goal,
                 json.dumps(plan, ensure_ascii=False), status, _now()),
            )
            return int(cur.lastrowid)

    def list_by_session(self, session_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM plans WHERE session_id = ? ORDER BY id DESC", (session_id,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["plan"] = json.loads(d.pop("plan_json"))
            except Exception:  # noqa: BLE001
                d["plan"] = {}
            out.append(d)
        return out

    def delete(self, plan_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
            return cur.rowcount > 0


plan_store = PlanStore()


# ---------------------------------------------------------------------------
# 规划核心（供工具与评测共用）
# ---------------------------------------------------------------------------
def _resolve_game(ctx: ToolContext, args: dict) -> Game:
    gid = str(args.get("game") or "").strip().lower()
    if gid in ("genshin", "arknights"):
        try:
            return registry.get_game(gid)
        except Exception:  # noqa: BLE001
            pass
    return ctx.game


def _fetch_character(game: Game, name: str) -> dict:
    """从动态缓存/静态库加载角色实体（与原神 133 角色、方舟干员一致）"""
    from app.tools.game_entity import QueryGameEntityTool

    res = QueryGameEntityTool().run(
        {"game": game.game_id, "type": "character", "name": name}, ToolContext(game))
    if isinstance(res, dict) and res.get("found") and res.get("entity"):
        return res["entity"]
    return {}


def _gacha_and_events(game_id: str) -> dict:
    """从 events_cache 聚合当前卡池与活动（跨源数据之一）"""
    cache = _load_json(DATA_DIR / "events_cache.json")
    for g in cache.get("games", []):
        if g.get("game_id") != game_id:
            continue
        gacha = None
        activities = []
        for ev in g.get("events", []):
            if ev.get("type") == "gacha" and ev.get("status") == "active":
                days = _days_left(ev.get("end", ""))
                gacha = {
                    "title": ev.get("title", ""),
                    "end": ev.get("end", ""),
                    "days_left": days,
                    "note": ev.get("note", ""),
                }
            elif ev.get("type") == "activity" and ev.get("status") == "active":
                activities.append({
                    "title": ev.get("title", ""),
                    "end": ev.get("end", ""),
                    "days_left": _days_left(ev.get("end", "")),
                })
        return {"gacha": gacha, "activities": activities[:5]}
    return {"gacha": None, "activities": []}


def build_primogem_budget(budget: int | None, days_left: int, activities: list[dict]) -> dict:
    """原石预算测算（原神）：当前持有 + 可攒估算 → 结论（小保底/大保底/缺口）"""
    current = int(budget or 0)
    earnable = days_left * DAILY_PRIMOGEM + ABYSS_PRIMOGEM + len(activities) * EVENT_PRIMOGEM_EST
    total = current + earnable
    if total >= PITY_HARD:
        conclusion = f"当前 {current:,} + 可攒约 {earnable:,} ≥ 大保底 {PITY_HARD:,}，稳拿当期"
    elif total >= PITY_SOFT:
        conclusion = f"当前 {current:,} + 可攒约 {earnable:,} 够小保底（{PITY_SOFT:,}），大保底缺口 {PITY_HARD - total:,}"
    else:
        conclusion = f"当前 {current:,} + 可攒约 {earnable:,}，距小保底还差 {PITY_SOFT - total:,}"
    return {
        "current": current,
        "earnable_est": earnable,
        "total_est": total,
        "pity_soft": PITY_SOFT,
        "pity_hard": PITY_HARD,
        "conclusion": conclusion,
    }


def build_materials(entity: dict, level_target: int, talent_target: int) -> list[dict]:
    """养成材料清单（原神）：通用常量 × 角色元素，输出带 note 口径"""
    element = entity.get("element", "")
    gem = GEM_BY_ELEMENT.get(element)
    materials: list[dict] = []
    if level_target >= 90:
        materials.append({"name": "摩拉", "count": ASCENSION_MORA,
                          "note": "角色 1→90 突破+升级（不含天赋/武器）"})
        materials.append({"name": "大英雄的经验", "count": ASCENSION_BOOKS,
                          "note": f"约 {ASCENSION_EXP:,} 经验"})
        if gem:
            for k, v in GEM_COUNTS.items():
                materials.append({"name": f"{gem}·{k}", "count": v,
                                  "note": "元素宝石（按角色元素）"})
        materials.append({"name": "地区特产", "count": LOCAL_SPECIALTY_COUNT,
                          "note": "具体特产按角色地区（如璃月=琉璃百合/霓裳花等），以游戏内为准"})
        materials.append({"name": "首领突破材料", "count": BOSS_MATERIAL_COUNT,
                          "note": "周常首领掉落"})
        materials.append({"name": "怪物材料", "count": COMMON_MATERIAL_COUNT,
                          "note": "突破所需（具体种类按角色，以游戏内为准）"})
    if talent_target in TALENT_BOOKS:
        t, g, p = TALENT_BOOKS[talent_target]
        skills = entity.get("skills") or []
        active_count = max(1, len(skills))
        materials.append({"name": "天赋书·教导", "count": t * active_count,
                          "note": f"天赋 1→{talent_target}，按 {active_count} 个主动天赋估算"})
        materials.append({"name": "天赋书·引导", "count": g * active_count,
                          "note": f"天赋 1→{talent_target}"})
        materials.append({"name": "天赋书·哲学", "count": p * active_count,
                          "note": f"天赋 1→{talent_target}"})
        materials.append({"name": "摩拉（天赋）", "count": TALENT_MORA[talent_target] * active_count,
                          "note": f"单天赋累计摩拉 {TALENT_MORA[talent_target]:,} × {active_count}"})
    return materials


def build_plan_steps(game_id: str, character: str, budget: dict | None,
                     gacha: dict | None, materials: list[dict]) -> list[dict]:
    """多步排期：卡池期攒原石 → 抽取 → 突破 → 天赋 → 养成收尾"""
    steps: list[dict] = []
    if game_id == "genshin" and budget:
        if gacha:
            steps.append({"step": 1, "action": f"卡池期（剩约 {gacha.get('days_left', 0)} 天）攒原石",
                          "detail": budget["conclusion"]})
        else:
            steps.append({"step": 1, "action": "攒原石", "detail": budget["conclusion"]})
        steps.append({"step": 2, "action": "抽取目标角色", "detail": f"{character}：小保底 {PITY_SOFT:,} / 大保底 {PITY_HARD:,} 原石"})
    steps.append({"step": max(1, len(steps) + 1), "action": "突破与升级",
                  "detail": "按元素宝石→首领材料→怪物材料→特产的顺序准备"})
    steps.append({"step": max(1, len(steps) + 1), "action": "天赋升级",
                  "detail": "天赋书 + 摩拉（见材料清单）"})
    steps.append({"step": max(1, len(steps) + 1), "action": "武器/圣遗物收尾",
                  "detail": "武器突破材料与圣遗物词条以攻略为准（可调 search_guides 查看）"})
    return steps


# ---------------------------------------------------------------------------
# 工具 1：养成规划
# ---------------------------------------------------------------------------
class BuildBuildPlanTool(Tool):
    name = "build_build_plan"
    description = (
        "生成角色的养成规划：资源预算（当前原石够不够抽当期卡池、可攒估算、保底对比）"
        "+ 养成材料清单（摩拉/经验/元素宝石/特产/天赋书）+ 多步排期。"
        "用户问「帮我规划抽XX/养成XX到90级/原石够不够/天赋书要多少」时调用，"
        "传游戏与角色名（primogem_budget=当前持有原石，talent_target=天赋目标如 9/9/9）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "game": {"type": "string", "enum": ["genshin", "arknights"],
                     "description": "游戏标识：原神=genshin，明日方舟=arknights"},
            "character": {"type": "string", "description": "目标角色/干员名称"},
            "primogem_budget": {"type": "integer",
                                "description": "当前持有原石数量（可空；仅原神使用）"},
            "level_target": {"type": "integer", "description": "目标等级，默认 90"},
            "talent_target": {"type": "string",
                              "description": "天赋目标，如 9/9/9 或 10/10/10（取最大值解析）"},
        },
        "required": ["game", "character"],
    }

    def run(self, args: dict, ctx: ToolContext) -> Any:
        game = _resolve_game(ctx, args)
        character = str(args.get("character") or "").strip()
        if not character:
            return {"found": False, "error": "缺少 character"}
        entity = _fetch_character(game, character)
        if not entity:
            return {"found": False, "error": f"未收录「{character}」的角色资料，无法规划",
                    "guides_hint": "可先查询角色或查看攻略视频"}

        budget = int(args.get("primogem_budget") or 0)
        level_target = min(int(args.get("level_target") or 90), 90)
        tt_raw = str(args.get("talent_target") or "9/9/9")
        talent_target = 10 if any(int(x) >= 10 for x in tt_raw.replace("/", " ").split() if x.strip().isdigit()) else 9

        plan: dict = {"game": game.game_id, "character": character, "found": True,
                      "rarity": entity.get("rarity"), "element": entity.get("element"),
                      "weapon_type": entity.get("weapon_type")}

        if game.game_id == "genshin":
            ce = _gacha_and_events(game.game_id)
            plan["gacha"] = ce["gacha"]
            plan["activities"] = ce["activities"]
            plan["budget"] = build_primogem_budget(
                budget, (ce["gacha"] or {}).get("days_left", 0), ce["activities"])
        else:
            # 方舟：资源测算不适用，材料统计复用 calculate_materials 数据
            from app.tools.strategy_tools import CalculateMaterialsTool
            mat = CalculateMaterialsTool().run({"game": "arknights", "name": character}, ToolContext(game))
            plan["materials_note"] = mat if isinstance(mat, dict) else {"error": "材料统计不可用"}

        plan["materials"] = build_materials(entity, level_target, talent_target)
        plan["steps"] = build_plan_steps(game.game_id, character, plan.get("budget"),
                                         plan.get("gacha"), plan["materials"])
        plan["disclaimer"] = DISCLAIMER
        return plan


# ---------------------------------------------------------------------------
# 工具 2：保存计划（写操作闭环）
# ---------------------------------------------------------------------------
class SaveBuildPlanTool(Tool):
    name = "save_build_plan"
    description = (
        "把养成规划持久化到当前会话（SQLite plans 表），之后可通过 /api/plans 回读。"
        "用户确认「按这个计划来/记下这个计划」时调用，参数与 build_build_plan 相同，"
        "goal 描述计划目标（如「胡桃 5.0 抽卡+90 级养成」）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "game": {"type": "string", "enum": ["genshin", "arknights"], "description": "游戏标识"},
            "character": {"type": "string", "description": "目标角色/干员名称"},
            "goal": {"type": "string", "description": "计划目标描述（可空）"},
            "primogem_budget": {"type": "integer", "description": "当前持有原石（可空）"},
            "talent_target": {"type": "string", "description": "天赋目标，默认 9/9/9"},
        },
        "required": ["game", "character"],
    }

    def run(self, args: dict, ctx: ToolContext) -> Any:
        if not ctx.session_id:
            return {"saved": False,
                    "error": "缺少会话上下文，无法保存（请在会话内发起规划后再确认保存）"}
        game = _resolve_game(ctx, args)
        character = str(args.get("character") or "").strip()
        if not character:
            return {"saved": False, "error": "缺少 character"}
        plan = BuildBuildPlanTool().run(args, ctx)
        if not plan.get("found"):
            return plan
        goal = str(args.get("goal") or f"{character} 养成规划").strip()
        plan_id = plan_store.save(ctx.session_id, game.game_id, character, goal, plan)
        return {"saved": True, "plan_id": plan_id, "status": "planned",
                "character": character, "goal": goal,
                "summary": f"已保存「{character}」养成计划（编号 {plan_id}），可通过 /api/plans?session_id= 回读"}
