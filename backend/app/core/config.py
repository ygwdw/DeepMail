"""系统级配置（基于 pydantic-settings）。

读取顺序：环境变量 > .env > 默认值。
用户级 LLM 配置存在 llm_configs 表，不在本文件。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- 应用基础 ---
    app_env: str = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_secret_key: str = "dev-secret-change-me"

    # --- 数据库 ---
    database_url: str = "postgresql+asyncpg://deepmail:deepmail@localhost:5432/deepmail"

    # --- JWT ---
    jwt_secret: str = "dev-jwt-secret-change-me-to-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 60
    jwt_refresh_ttl_days: int = 7

    # --- 管理员初始账号（仅首次 seed 时使用）---
    admin_username: str = "admin"
    admin_password: str = "ChangeMe@2026"

    # --- LLM 默认配置（用户可在 UI 覆盖）---
    llm_provider: str = "openai_compatible"
    llm_base_url: str = "https://api.minimaxi.com/v1"
    llm_api_key: str = "sk-cp-Gb33ogf3nB4A25rqU1QRyk5qVIfr6MkgWrkXhKic8yzJOvcwCMue1pj_oS6V17nz8i0VjeMpo0Rciq5JmaY_PkI5edD7-ENPx80z21NmdDyPvgI4wuRfBzE"
    llm_chat_model: str = "MiniMax-M3"

    # --- Embedding / Reranker（Gitee AI 服务）---
    embed_base_url: str = "https://ai.gitee.com/v1"
    embed_api_key: str = "7U7QJFRWQ972H6PARAURUC1G7HU1DYA9IQL9K21D"
    llm_embed_model: str = "Qwen3-Embedding-0.6B"
    rerank_base_url: str = "https://ai.gitee.com/v1"
    rerank_api_key: str = "7U7QJFRWQ972H6PARAURUC1G7HU1DYA9IQL9K21D"
    llm_rerank_model: str = "Qwen3-Reranker-0.6B"
    llm_embed_dim: int = 1024

    # --- Mock 邮件 ---
    mock_emails_dir: str = "./data/mock_emails"

    # --- 日志 ---
    log_level: str = "INFO"

    # --- LangSmith 可观测性 ---
    langsmith_api_key: str = ""  # 留空 = 关闭
    langsmith_project: str = "deepmail"
    langsmith_endpoint: str = ""  # 留空用 langsmith 默认


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """单例 Settings。"""
    return Settings()  # type: ignore[call-arg]


def project_root() -> Path:
    """返回项目根目录（pyproject.toml 所在）。"""
    # backend/app/core/config.py → backend/app/core → backend/app → backend → root
    return Path(__file__).resolve().parents[3]


def resolve_path(rel_or_abs: str) -> Path:
    """将相对路径解析为相对项目根的绝对路径。"""
    p = Path(rel_or_abs)
    if p.is_absolute():
        return p
    return project_root() / p
