"""应用配置：从环境变量 / .env 加载"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置。字段与 .env.example 一一对应。"""

    app_name: str = "AI 游戏助手智能体平台"
    debug: bool = True
    log_level: str = "INFO"

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    deepseek_reasoner_model: str = "deepseek-reasoner"

    # RAG
    embedding_model: str = "BAAI/bge-small-zh-v1.5"   # 中文轻量 embedding（512 维，约 95MB）
    embedding_cache_dir: str = "models/embeddings"     # 模型本地缓存目录
    retrieval_top_k: int = 5
    retrieval_score_threshold: float = 0.5  # TODO: 按评测结果调优

    # 路径
    chroma_dir: str = "data/chroma"
    sqlite_path: str = "data/sessions.db"
    games_config: str = "config/games.yaml"

    # Agent 可靠性
    node_max_retries: int = 2
    node_timeout_seconds: int = 30

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """进程内单例配置"""
    return Settings()


settings = get_settings()
