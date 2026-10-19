"""多模态上传接口：接收游戏截图 → 存本地 → 返回路径供聊天消息携带

- POST /api/vision/upload   multipart 上传（jpg/png/webp，≤10MB）
- 静态访问: /uploads/<文件名>（前端预览）
"""
import asyncio
import time
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, UploadFile

from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/vision", tags=["vision"])

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_MAX_BYTES = 10 * 1024 * 1024  # 10MB


@router.post("/upload")
async def upload_image(file: UploadFile = File(...)):  # noqa: B008 - FastAPI 依赖注入的标准写法
    """上传游戏截图，返回本地路径与预览 URL（随后随消息 image_path 提交）"""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = (file.filename or "screenshot.png").replace("\\", "/").split("/")[-1]
    ext = Path(name).suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise AppError(ErrorCode.INVALID_REQUEST, f"不支持的图片格式（支持 {'/'.join(sorted(_ALLOWED_EXT))}）")
    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise AppError(ErrorCode.INVALID_REQUEST, "图片过大（上限 10MB），请压缩后重试")

    safe_name = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}{ext}"
    target = UPLOAD_DIR / safe_name
    # 落盘是阻塞 IO，放到线程池，避免大图上传卡住事件循环
    await asyncio.to_thread(target.write_bytes, data)
    logger.info("upload ok: %s (%d bytes)", safe_name, len(data))
    return {
        "ok": True,
        "image_path": str(target),
        "image_url": f"/uploads/{safe_name}",
        "size": len(data),
    }
