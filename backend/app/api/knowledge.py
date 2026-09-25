"""知识库补充接口

- POST /api/knowledge/feedback  用户提交"补充资料"请求（未收录实体 → 待人工核实入库）

数据落盘：backend/data/<game_id>/feedback/feedback.jsonl（追加行，供后续批量核实脚本入库）。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.knowledge.games import registry

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

BACKEND = Path(__file__).resolve().parent.parent.parent


class FeedbackRequest(BaseModel):
    """补充资料请求：记录未收录实体的名称与用户补充说明"""

    game_id: str = Field(..., description="游戏标识：genshin / arknights")
    entity_name: str = Field(..., min_length=1, max_length=100, description="未收录实体名称")
    note: Optional[str] = Field(None, max_length=500, description="用户补充说明（可空）")


@router.post("/feedback")
def submit_feedback(body: FeedbackRequest):
    gid = (body.game_id or "").strip().lower()
    if gid not in ("genshin", "arknights"):
        raise HTTPException(status_code=400, detail="无效的 game_id")
    try:
        game = registry.get_game(gid)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="游戏不存在")

    fb_dir = game.data_dir / "feedback"
    fb_dir.mkdir(parents=True, exist_ok=True)
    path = fb_dir / "feedback.jsonl"
    record = {
        "game_id": gid,
        "entity_name": body.entity_name.strip(),
        "note": (body.note or "").strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True, "record": record}
