# -*- coding: utf-8 -*-
"""get_game_events：查询游戏重大事件（版本更新/活动/卡池/前瞻）并返回倒计时

数据来自 events/engine.py（官方 wiki 抓取 + 推算），带 30 分钟缓存。
查询时区分当前游戏（ctx.game 注入），支持类型过滤。不编造：未收录返回空列表并注明。
"""
from typing import Any

from app.events.engine import build_events
from app.tools.base import Tool, ToolContext

VALID_TYPES = ("version_update", "maintenance", "activity", "gacha", "gacha_weapon", "livestream")


class GetGameEventsTool(Tool):
    name = "get_game_events"
    description = (
        "查询当前游戏的重大事件排期：版本更新/维护、限时活动、卡池（祈愿）开放、前瞻直播，"
        "返回事件名称、起止时间、状态（进行中/即将开始）与剩余倒计时。"
        "适用于用户问『最近有什么活动/卡池/维护/版本更新/前瞻』等时效性问题。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "types": {
                "type": "array",
                "items": {"type": "string", "enum": list(VALID_TYPES)},
                "description": "事件类型过滤（可选）。不传返回全部事件。",
            },
            "limit": {
                "type": "integer",
                "description": "返回条数上限（可选，默认 10）",
            },
        },
    }

    def run(self, args: dict, ctx: ToolContext) -> Any:
        types = args.get("types") or list(VALID_TYPES)
        limit = int(args.get("limit") or 10)
        try:
            games = build_events()
        except Exception as e:  # noqa: BLE001
            return {
                "game": ctx.game.game_id,
                "ok": False,
                "events": [],
                "note": f"事件服务暂不可用（{e}），请稍后再试",
            }
        game_evs = next((g for g in games if g["game_id"] == ctx.game.game_id), None)
        if not game_evs:
            return {
                "game": ctx.game.game_id,
                "ok": True,
                "events": [],
                "note": "该游戏暂无已公布事件排期",
            }
        events = [e for e in game_evs.get("events", []) if e.get("type") in types]
        out = []
        for e in events[:limit]:
            out.append({
                "type": e.get("type"),
                "title": e.get("title"),
                "status": e.get("status"),
                "start": e.get("start"),
                "end": e.get("end"),
                "estimated": e.get("estimated", False),
                "note": e.get("note", ""),
                "countdown": (
                    f"{int(e['countdown_sec'] // 86400)}天{int(e['countdown_sec'] % 86400 // 3600)}小时"
                    if e.get("countdown_sec") is not None else "进行中（待官方公告）"
                ),
            })
        return {
            "game": ctx.game.game_id,
            "ok": True,
            "count": len(out),
            "events": out,
            "note": "数据来自官方 wiki（bwiki），未收录的不编造",
        }
