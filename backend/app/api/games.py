"""游戏相关接口：游戏列表（前端选择器数据源）"""
from fastapi import APIRouter

from app.knowledge.games import registry

router = APIRouter(prefix="/api/games", tags=["games"])


@router.get("")
def list_games():
    """返回启用的游戏列表"""
    return {"games": registry.list_games(only_enabled=True)}
