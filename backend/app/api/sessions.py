"""会话接口：创建 / 列表 / 历史消息"""
from fastapi import APIRouter

from app.knowledge.games import registry
from app.memory.store import store
from app.schemas.chat import SessionCreate, SessionInfo

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionInfo])
def list_sessions(game_id: str | None = None):
    """会话列表，可按游戏过滤"""
    return store.list_sessions(game_id)


@router.post("", response_model=SessionInfo)
def create_session(body: SessionCreate):
    """新建会话（校验游戏存在且启用）"""
    game = registry.get_game(body.game_id)
    return store.create_session(game.game_id, title=body.title or f"{game.name} 新会话")


@router.get("/{session_id}/messages")
def get_messages(session_id: str, limit: int | None = None):
    """获取会话历史消息"""
    store.get_session(session_id)  # 不存在则抛 404 语义错误
    return {"messages": store.get_messages(session_id, limit=limit)}


@router.delete("/{session_id}")
def delete_session(session_id: str):
    """删除会话（含全部消息）"""
    store.delete_session(session_id)
    return {"ok": True}
