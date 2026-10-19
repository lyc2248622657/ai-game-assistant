"""接口鉴权：本机回环免令牌 + 令牌保护一切外部访问。

威胁模型
--------
这是一个**单用户、本地优先**的工具，但它带了若干破坏性接口
（`POST /api/vector/purge` 清空向量、`DELETE /api/vector/documents/*`、
`PUT /api/settings/key` 写 API Key、`DELETE /api/plans/*`）。
一旦通过 `--host 0.0.0.0`、Docker 端口映射或反向代理暴露出去，
同网段任何人都能直接调用这些接口。

策略（默认即可用，暴露才收紧张力最小）
--------
1. **本机回环**（127.0.0.1 / ::1）默认免令牌 —— 双击 EXE、本地开发零配置；
2. **非回环来源**必须携带令牌，否则 401；令牌在首次需要时自动生成并落盘
   `app_data/.api_token`（也可用 `API_TOKEN` 环境变量显式指定，适合 Docker/CI）；
3. `TRUST_LOOPBACK=false` 可让本机也强制校验（远程桌面、多人共用主机时用）；
4. 令牌支持三种传递方式：`Authorization: Bearer <t>`、`X-API-Token: <t>`、`?token=<t>`
   （查询参数是给 `<img src="/uploads/...">` 这类无法自定义请求头的场景准备的）；
5. 同一来源 IP 鉴权失败过多返回 429，降低暴力猜测速度。

令牌只在**回环请求**下通过 `/api/auth/status` 返回，方便本机页面自动填充；
远端永远拿不到明文。
"""
from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.errors import ErrorCode
from app.core.key_manager import app_data_dir
from app.core.logging import get_logger

logger = get_logger(__name__)

# 令牌文件（首次使用时生成；已在 .gitignore 的 app_data/ 下）
TOKEN_FILE: Path = app_data_dir() / ".api_token"

# 不需要鉴权的路径前缀：健康检查 + 鉴权状态（前端据此弹出令牌输入）
EXEMPT_PREFIXES = ("/api/health", "/api/auth/status")

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
_token_cache: dict[str, str] = {}
_fail_log: dict[str, list[float]] = {}
_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# 令牌管理
# --------------------------------------------------------------------------- #
def mask_token(token: str) -> str:
    """打码展示：abcd****wxyz（日志与远端响应都只出现这个形式）"""
    if not token:
        return ""
    if len(token) <= 10:
        return "*" * len(token)
    return f"{token[:4]}****{token[-4:]}"


def load_token() -> str:
    """解析令牌：环境变量 > app_data/.api_token（不存在则生成并落盘）"""
    explicit = (settings.api_token or "").strip()
    if explicit:
        return explicit
    if TOKEN_FILE.exists():
        try:
            token = TOKEN_FILE.read_text(encoding="utf-8").strip()
            if token:
                return token
        except OSError as e:  # noqa: BLE001
            logger.warning("读取令牌文件失败，将重新生成: %s", e)
    token = secrets.token_urlsafe(32)
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
        try:
            TOKEN_FILE.chmod(0o600)
        except OSError:
            pass  # Windows 上 chmod 语义有限，忽略
        logger.warning(
            "未配置 API_TOKEN，已自动生成访问令牌并写入 %s（非本机访问需要它）", TOKEN_FILE
        )
    except OSError as e:  # noqa: BLE001
        logger.error("令牌文件写入失败，本次使用内存令牌（重启即失效）: %s", e)
    return token


def current_token() -> str:
    """进程内缓存令牌，避免每个请求都读文件"""
    if "value" not in _token_cache:
        _token_cache["value"] = load_token()
    return _token_cache["value"]


def rotate_token() -> str:
    """重新生成令牌（本机回环可用），已连接的外部客户端会立即失效"""
    token = secrets.token_urlsafe(32)
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    except OSError as e:  # noqa: BLE001
        logger.error("令牌落盘失败（仅内存生效）: %s", e)
    _token_cache["value"] = token
    with _lock:
        _fail_log.clear()
    logger.warning("访问令牌已轮换（%s）", mask_token(token))
    return token


def verify_token(presented: str | None) -> bool:
    """常量时间比较，避免时序侧信道"""
    if not presented:
        return False
    return secrets.compare_digest(str(presented), current_token())


# --------------------------------------------------------------------------- #
# 来源判定与限流
# --------------------------------------------------------------------------- #
def is_loopback(host: str | None) -> bool:
    return (host or "") in _LOOPBACK_HOSTS


def is_exempt(path: str) -> bool:
    return any(path.startswith(p) for p in EXEMPT_PREFIXES)


def needs_auth(path: str) -> bool:
    """只保护 API 与用户上传物；前端静态资源必须开放，否则页面加载不出来也就没法输入令牌"""
    return path.startswith("/api/") or path.startswith("/uploads/")


def extract_token(headers: Headers, query_string: bytes) -> str | None:
    auth = headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    token = headers.get("x-api-token")
    if token:
        return token.strip()
    if query_string:
        qs = parse_qs(query_string.decode("latin-1"))
        vals = qs.get("token") or qs.get("api_token")
        if vals:
            return vals[0].strip()
    return None


def _too_many_failures(host: str) -> bool:
    """窗口 60s 内失败次数超过阈值 → 429"""
    now = time.time()
    with _lock:
        records = [t for t in _fail_log.get(host, []) if now - t < 60]
        _fail_log[host] = records
        return len(records) >= max(1, int(settings.auth_fail_limit))


def record_failure(host: str) -> None:
    with _lock:
        _fail_log.setdefault(host, []).append(time.time())


def reset_failures(host: str) -> None:
    with _lock:
        _fail_log.pop(host, None)


# --------------------------------------------------------------------------- #
# ASGI 中间件（纯 ASGI：不缓冲响应体，SSE 流式不受影响）
# --------------------------------------------------------------------------- #
class AuthMiddleware:
    """非回环请求的令牌校验。放行条件（任一即可）：

    - 路径不需要鉴权（静态资源、健康检查、鉴权状态）
    - `TRUST_LOOPBACK=true` 且来源是回环地址
    - 携带了正确的令牌
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not needs_auth(path) or is_exempt(path):
            await self.app(scope, receive, send)
            return

        client = scope.get("client") or ("", 0)
        host = client[0] if isinstance(client, (tuple, list)) and client else ""
        # 回环免令牌的前提是"直连"：若请求带了 X-Forwarded-For，
        # 说明它经过反向代理，而反代与后端同机时 TCP 对端同样是 127.0.0.1 ——
        # 此时不能把"反代转发的公网请求"误判为本机请求。
        if settings.trust_loopback and is_loopback(host) and not Headers(scope=scope).get("x-forwarded-for"):
            await self.app(scope, receive, send)
            return

        token = extract_token(Headers(scope=scope), scope.get("query_string") or b"")
        if verify_token(token):
            reset_failures(host)
            await self.app(scope, receive, send)
            return

        if _too_many_failures(host):
            response = JSONResponse(
                status_code=429,
                content={"code": ErrorCode.UNAUTHORIZED.value, "message": "鉴权失败次数过多，请稍后重试"},
            )
        else:
            record_failure(host)
            logger.warning("拒绝未授权访问: %s %s（来源 %s）", scope.get("method"), path, host)
            response = JSONResponse(
                status_code=401,
                content={
                    "code": ErrorCode.UNAUTHORIZED.value,
                    "message": "需要访问令牌：请在设置中填写，或从服务端 app_data/.api_token 获取",
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
        await response(scope, receive, send)
