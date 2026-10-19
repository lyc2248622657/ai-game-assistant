"""养成计划接口：按会话回读 / 删除（写操作闭环的对外窗口）"""
from fastapi import APIRouter, Query

from app.core.errors import AppError, ErrorCode
from app.tools.build_plan import plan_store

router = APIRouter(prefix="/api/plans", tags=["plans"])


@router.get("")
def list_plans(session_id: str = Query(..., description="会话 ID")):
    """按会话列出已保存的养成计划"""
    return {"plans": plan_store.list_by_session(session_id)}


@router.delete("/{plan_id}")
def delete_plan(plan_id: int, session_id: str = Query(..., description="会话 ID（用于校验归属）")):
    """删除指定养成计划（必须带 session_id，且计划需属于该会话）

    原实现只按 plan_id 删除，任何客户端都能删别人会话下的计划；
    GET 反而要求 session_id，契约本身也自相矛盾。
    """
    if not plan_store.delete(plan_id, session_id=session_id):
        raise AppError(ErrorCode.INVALID_REQUEST, f"计划不存在或不属于该会话: {plan_id}", 404)
    return {"ok": True}
