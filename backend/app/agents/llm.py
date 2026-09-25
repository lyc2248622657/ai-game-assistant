"""LLM 工厂：DeepSeek（OpenAI 兼容接口）"""
from functools import lru_cache

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


@lru_cache
def get_chat_model():
    if not settings.deepseek_api_key or settings.deepseek_api_key.startswith("sk-xxx"):
        logger.warning("未配置 DEEPSEEK_API_KEY，Agent 将无法调用模型（请配置 backend/.env）")
    return build_chat_model()
