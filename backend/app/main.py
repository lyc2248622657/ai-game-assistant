"""FastAPI 应用入口"""
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import auth as auth_api
from app.api import chat, docqa, events, games, knowledge, plans, sessions
from app.api import settings as settings_api
from app.api import vector_admin, vision
from app.core.auth import AuthMiddleware, current_token, mask_token
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="基于 LangGraph 的多智能体游戏助手 · 大模型应用开发（Agent 方向）",
)

# 接口鉴权：非回环来源必须带令牌（本机回环默认免令牌）。
# 放在最外层，先于所有路由生效；纯 ASGI 实现，不影响 SSE 流式。
app.add_middleware(AuthMiddleware)
logger.info(
    "接口鉴权已启用：本机回环%s，令牌 %s（来源 app_data/.api_token 或 API_TOKEN）",
    "免校验" if settings.trust_loopback else "也需校验",
    mask_token(current_token()),
)

app.include_router(auth_api.router)
app.include_router(games.router)
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(knowledge.router)
app.include_router(events.router)
app.include_router(docqa.router)
app.include_router(vector_admin.router)
app.include_router(settings_api.router)
app.include_router(vision.router)
app.include_router(plans.router)

# 多模态：上传截图静态访问（/uploads/xxx 预览）
_uploads = Path(__file__).resolve().parent.parent / "data" / "uploads"
try:
    _uploads.mkdir(parents=True, exist_ok=True)
except OSError as e:  # 只读文件系统下不应阻断服务启动
    logger.warning("上传目录创建失败（只读文件系统？）: %s", e)
from fastapi.staticfiles import StaticFiles as _StaticFiles

if _uploads.exists():
    app.mount("/uploads", _StaticFiles(directory=str(_uploads)), name="uploads")


@app.get("/api/health")
def health():
    """健康检查"""
    return {"status": "ok", "app": settings.app_name}


# 未知 /api/* 路径 → 统一 JSON 404
# （否则会被下面的前端静态挂载"吞掉"，返回 index.html 或纯文本 404，破坏前端错误处理）
@app.api_route(
    "/api/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    include_in_schema=False,
)
def api_not_found(path: str):
    raise AppError(ErrorCode.INVALID_REQUEST, f"接口不存在: /api/{path}", 404)


def _static_dir() -> Path:
    """前端静态资源目录：PyInstaller 打包 = _MEIPASS/frontend_dist；开发 = frontend/dist"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", ".")) / "frontend_dist"
    return Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


# 挂载前端静态资源（单页应用：/ 返回 index.html；须在 API 路由之后注册）
_static = _static_dir()
if _static.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
    logger.info("前端静态资源已挂载: %s", _static)
else:
    logger.warning("前端静态目录不存在（仅 API 模式）: %s", _static)


# ---------- 统一错误响应契约：{"code": <int>, "message": <str>} ----------
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code.value, "message": exc.message},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """请求体/参数校验失败 → 与业务错误同一形状（原先是 FastAPI 默认的 {"detail": [...]}）"""
    first = (exc.errors() or [{}])[0]
    loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
    msg = first.get("msg", "请求参数非法")
    return JSONResponse(
        status_code=422,
        content={
            "code": ErrorCode.INVALID_REQUEST.value,
            "message": f"{loc}: {msg}" if loc else msg,
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """路由未命中 / 方法不允许等框架级 HTTP 异常也统一成 {code, message}"""
    code = ErrorCode.INTERNAL if exc.status_code >= 500 else ErrorCode.INVALID_REQUEST
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": code.value, "message": str(exc.detail)},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("未处理异常: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"code": ErrorCode.INTERNAL.value, "message": "服务器内部错误"},
    )


if __name__ == "__main__":
    import uvicorn

    # 默认只监听回环地址；若确实要暴露到局域网，请先设置 API_TOKEN（见 README「接口鉴权」）
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=settings.debug)
