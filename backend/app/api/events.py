# -*- coding: utf-8 -*-
"""游戏重大事件倒计时 API：GET /api/events"""
import asyncio

from fastapi import APIRouter

from app.events.engine import build_events

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
async def list_events():
    """各游戏重大事件 + 倒计时（版本更新/前瞻直播/活动/卡池）

    抓取是串行的多路 HTTP（最坏数十秒），放到线程池执行，避免占用事件循环。
    """
    return {"games": await asyncio.to_thread(build_events)}
