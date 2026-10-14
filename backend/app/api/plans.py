"""养成计划接口：按会话回读 / 删除（写操作闭环的对外窗口）"""
from fastapi import APIRouter, Query

from app.tools.build_plan import plan_store

router = APIRouter(prefix="/api/plans", tags=["plans"])


@router.get("")
def list_plans(session_id: str = Query(..., description="会话 ID")):
    """按会话列出已保存的养成计划"""
    return {"plans": plan_store.list_by_session(session_id)}


@router.delete("/{plan_id}")
def delete_plan(plan_id: int):
    """删除指定养成计划"""
    return {"ok": plan_store.delete(plan_id)}
