"""Embedding 工厂：bge-small-zh-v1.5 本地向量化（fastembed / ONNX，无 torch）

设计说明：
  - DeepSeek 官方 API 不提供 embedding 接口，故本地部署开源中文 embedding；
  - bge-small-zh-v1.5：约 95MB、512 维，中文检索效果好、推理快（ONNX Runtime）；
  - 相对原方案（bge-m3 + sentence-transformers ≈ 2GB）显著轻量；
  - 首次加载自动下载模型，懒加载不影响服务启动；
  - 统一 encode 接口，未来可替换为在线 embedding API 或 Chroma 默认函数。
"""
import os
from functools import lru_cache

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# HuggingFace 国内网络：走镜像 + 禁用 xet 传输（普通 HTTP 下载）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"


class EmbeddingFactory:
    """按需加载 bge-small-zh，对外提供 encode 接口"""

    def __init__(self, model_name: str | None = None, cache_dir: str | None = None):
        self._model_name = model_name or settings.embedding_model or DEFAULT_MODEL
        self._cache_dir = cache_dir or str(settings.embedding_cache_dir)
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            logger.info("首次加载 embedding 模型: %s（缓存 %s）", self._model_name, self._cache_dir)
            from fastembed import TextEmbedding

            self._model = TextEmbedding(self._model_name, cache_dir=self._cache_dir)
            logger.info("embedding 模型加载完成（backend=fastembed/onnx）")
        return self._model

    def encode(self, texts: list[str]) -> list[list[float]]:
        """文本列表 → 向量列表（512 维）"""
        model = self._ensure_model()
        return [v.tolist() for v in model.embed(texts)]

    @property
    def dimension(self) -> int:
        return len(self.encode(["测试"])[0])


@lru_cache
def get_embedding() -> EmbeddingFactory:
    return EmbeddingFactory()
