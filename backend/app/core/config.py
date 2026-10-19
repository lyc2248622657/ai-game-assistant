"""应用配置：从环境变量 / .env 加载

路径约定（重要）：
  相对路径一律按 **backend/ 目录** 解析为绝对路径，而不是按进程 CWD 解析。
  原实现依赖"必须从 backend/ 启动"，导致从仓库根启动时 data/chroma、sessions.db
  会被静默创建到别处；打包/容器内的工作目录也各不相同。
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录（本文件 = backend/app/core/config.py）
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent

# 需要做"相对 backend/ 解析"的路径型配置
_PATH_FIELDS = ("embedding_cache_dir", "chroma_dir", "sqlite_path", "games_config", "documents_dir")


class Settings(BaseSettings):
    """全局配置。字段与 .env.example 一一对应。"""

    app_name: str = "AI 游戏助手智能体平台"
    debug: bool = False
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
    retrieval_score_threshold: float = 0.5  # 见 docs/框架问题排查报告.md：待按评测集标定
    # 只输出 JSON 的节点（主管/重规划/质检）限制输出长度：它们只需要几十个 token，
    # 不限制时模型容易长篇解释，纯属浪费
    llm_json_max_tokens: int = 512

    # 路径
    chroma_dir: str = "data/chroma"
    sqlite_path: str = "data/sessions.db"
    games_config: str = "config/games.yaml"
    # 企业文档问答语料目录：原先从 chroma_dir 反推（改 chroma_dir 会把语料整体搬走）
    documents_dir: str = "data/documents"

    # 接口鉴权：非本机回环访问必须携带令牌（本机回环默认免令牌，单机体验不变）
    api_token: str = ""          # 显式令牌；为空时自动生成到 app_data/.api_token
    trust_loopback: bool = True  # True = 127.0.0.1/::1 免令牌；改成 False 则本机也要令牌
    auth_fail_limit: int = 10    # 每个来源 IP 每分钟允许的鉴权失败次数（超出返回 429）

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    def model_post_init(self, __context) -> None:  # noqa: ANN001
        """把路径型配置统一解析为绝对路径（相对 backend/），消除对 CWD 的依赖。"""
        for field in _PATH_FIELDS:
            value = getattr(self, field)
            if not value:
                continue
            path = Path(value)
            if not path.is_absolute():
                setattr(self, field, str(BACKEND_ROOT / path))


@lru_cache
def get_settings() -> Settings:
    """进程内单例配置"""
    return Settings()


settings = get_settings()
