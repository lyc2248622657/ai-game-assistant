"""应用内设置 API：API Key 配置（填写/保存/测试），替代只读本地文件链

安全约定：响应只返回打码后的 key；明文仅用于保存到本地 settings.json 与运行时内存。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core import key_manager
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


class KeySaveRequest(BaseModel):
    api_key: str = Field(..., min_length=8, description="DeepSeek API Key（sk- 开头）")
    model: str = Field("deepseek-chat", description="模型类型")


class KeyTestRequest(BaseModel):
    api_key: str = Field(..., min_length=8)
    model: str = Field("deepseek-chat")


@router.get("/api/settings/key")
def get_key_status():
    """查询当前 Key 配置状态（只返回打码结果，绝不明文）"""
    saved = key_manager.load_saved()
    runtime_model, runtime_key = key_manager.resolve_runtime()
    if saved:
        return {
            "configured": True,
            "source": "app_settings",
            "model": saved[0],
            "masked_key": key_manager.mask_key(saved[1]),
        }
    if runtime_key:
        return {
            "configured": True,
            "source": "env_or_file",
            "model": runtime_model,
            "masked_key": key_manager.mask_key(runtime_key),
        }
    return {"configured": False, "source": None, "model": "", "masked_key": ""}


@router.put("/api/settings/key")
def save_key(req: KeySaveRequest):
    """保存应用内设置的 Key（持久化 settings.json 并即时生效，无需重启）"""
    api_key = req.api_key.strip()
    if not api_key.startswith("sk-"):
        raise HTTPException(status_code=400, detail="Key 应以 sk- 开头，请检查后重试")
    path = key_manager.save(req.model, api_key)
    logger.info("应用内设置已保存 API Key（%s）到 %s", key_manager.mask_key(api_key), path)
    return {
        "ok": True,
        "model": (req.model or "deepseek-chat").strip(),
        "masked_key": key_manager.mask_key(api_key),
        "message": "已保存并即时生效（无需重启）",
    }


@router.post("/api/settings/key/test")
def test_key(req: KeyTestRequest):
    """测试 Key 可用性（最小请求，不保存）"""
    ok, message = key_manager.test_key(req.api_key, req.model)
    return {"ok": ok, "message": message}
