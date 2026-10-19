"""接口鉴权状态接口（供前端判断是否需要输入访问令牌）"""
from fastapi import APIRouter, Request

from app.core import auth
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


def _client_host(request: Request) -> str:
    return request.client.host if request.client else ""


@router.get("/status")
def auth_status(request: Request):
    """鉴权状态（本接口豁免鉴权，否则前端无法发现"需要令牌"）

    - `auth_required`：本次请求是否本应需要令牌（非回环 / 强制模式）
    - `authorized`：当前请求是否已带有效令牌，或来源免鉴权
    - `token`：**仅回环来源**返回明文，方便本机页面自动填充；远端恒为 None
    """
    host = _client_host(request)
    loopback_free = settings.trust_loopback and auth.is_loopback(host)
    token = auth.extract_token(request.headers, request.scope.get("query_string") or b"")
    authorized = loopback_free or auth.verify_token(token)
    return {
        "auth_required": not loopback_free,
        "authorized": authorized,
        "loopback": auth.is_loopback(host),
        "token_configured": bool(auth.current_token()),
        "token": auth.current_token() if auth.is_loopback(host) else None,
    }


@router.post("/verify")
def verify(request: Request):
    """校验前端填写的令牌是否正确（不返回令牌本身）"""
    token = auth.extract_token(request.headers, request.scope.get("query_string") or b"")
    if not auth.verify_token(token):
        raise AppError(ErrorCode.UNAUTHORIZED, "访问令牌不正确")
    return {"ok": True}


@router.post("/rotate")
def rotate(request: Request):
    """重新生成访问令牌（仅回环来源；轮换后已连接的外部客户端立即失效）"""
    host = _client_host(request)
    if not auth.is_loopback(host):
        raise AppError(ErrorCode.UNAUTHORIZED, "仅允许在本机轮换访问令牌", 403)
    token = auth.rotate_token()
    logger.warning("访问令牌已由本机请求轮换（%s）", auth.mask_token(token))
    return {"ok": True, "token": token, "masked": auth.mask_token(token)}
