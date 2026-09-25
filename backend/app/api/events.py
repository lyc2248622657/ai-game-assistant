# -*- coding: utf-8 -*-
"""游戏重大事件倒计时 API：GET /api/events"""
from fastapi import APIRouter

from app.events.engine import build_events

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
def list_events():
    """各游戏重大事件 + 倒计时（版本更新/前瞻直播/活动/卡池）"""
    return {"games": build_events()}
