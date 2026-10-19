"""LLM 工厂：DeepSeek（OpenAI 兼容接口）

Key 来源（优先级）：应用内设置（settings.json，设置界面填写）> 环境变量/.env > 本地 key.txt 兜底。
key 变化时自动重建模型实例（无需重启）。
"""
from app.core import key_manager
from app.core.config import settings
from app.core.logging import get_logger
from app.core.usage import usage_stats

logger = get_logger(__name__)


def build_chat_model(**overrides):
    """构建 DeepSeek Chat 模型（langchain-openai 兼容，挂全局用量统计回调）"""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0.3,
        timeout=60,
        max_retries=1,
        callbacks=[usage_stats.handler],
        **overrides,
    )


_cached_model = None
_cached_sig: tuple[str, str] | None = None


def get_chat_model():
    """获取模型实例：key 或 model 任一变化即重建（应用内设置保存后即时生效）。

    缓存键用 (key, model) 元组——原实现只比较 key，
    于是"同一个 key 切模型"不会生效，"key 被清空"仍会复用旧实例。
    """
    global _cached_model, _cached_sig
    model, key = key_manager.resolve_runtime()
    if not key or key.startswith("sk-xxx"):
        logger.warning("未配置 DEEPSEEK_API_KEY，Agent 将无法调用模型（请在应用内设置界面填写）")
        return None

    sig = (key, model or settings.deepseek_model)
    if _cached_model is None or sig != _cached_sig:
        settings.deepseek_api_key = key
        if model:
            settings.deepseek_model = model
        _cached_model = build_chat_model()
        _cached_sig = sig
        logger.info("LLM 实例已重建（key=%s, model=%s）", key_manager.mask_key(key), settings.deepseek_model)
    return _cached_model
