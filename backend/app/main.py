"""FastAPI 应用入口"""
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import chat, events, games, knowledge, sessions
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

app.include_router(games.router)
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(knowledge.router)
app.include_router(events.router)


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


@app.get("/api/health")
def health():
    """健康检查"""
    return {"status": "ok", "app": settings.app_name}


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code.value, "message": exc.message},
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

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
