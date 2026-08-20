"""LLM 工厂：按用户配置 / 系统配置加载 langchain ChatModel。"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.llm.mock import MockLLM

_settings = get_settings()


@dataclass(frozen=True)
class LLMSettings:
    """运行时 LLM 配置（来自 settings 或 DB）。"""

    provider: str
    base_url: str
    api_key: str
    chat_model: str
    timeout_seconds: int = 30
    max_retries: int = 2


@dataclass(frozen=True)
class SystemLLMConfig:
    """从 .env 派生的系统默认配置。"""

    provider: str
    base_url: str
    api_key: str
    chat_model: str

    @classmethod
    def from_settings(cls) -> SystemLLMConfig:
        return cls(
            provider=_settings.llm_provider,
            base_url=_settings.llm_base_url,
            api_key=_settings.llm_api_key,
            chat_model=_settings.llm_chat_model,
        )

    def to_llm_settings(self) -> LLMSettings:
        return LLMSettings(
            provider=self.provider,
            base_url=self.base_url,
            api_key=self.api_key,
            chat_model=self.chat_model,
        )


def is_mock_mode() -> bool:
    """是否启用 Mock LLM（单测 / 集成测试 / 本地无 key）。"""
    if os.getenv("LLM_MOCK", "").lower() in ("1", "true", "yes"):
        return True
    return _settings.llm_api_key in ("", "replace-with-your-real-key")


async def get_user_llm_settings(db: AsyncSession, user_id: uuid.UUID) -> LLMSettings | None:
    """从 llm_configs 表读用户级配置（如果有）。"""
    from app.db.models.user import LLMConfig as UserLLMConfigRow

    stmt = select(UserLLMConfigRow).where(UserLLMConfigRow.user_id == user_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    return LLMSettings(
        provider=row.provider,
        base_url=row.base_url,
        api_key=row.api_key_encrypted,  # 阶段 1 明文存储；后续接入 Fernet
        chat_model=row.chat_model,
    )


def resolve_user_settings(user_cfg: LLMSettings | None) -> LLMSettings:
    """用户配置缺失字段时用系统默认补齐。"""
    sys_cfg = SystemLLMConfig.from_settings().to_llm_settings()
    if user_cfg is None:
        return sys_cfg
    return LLMSettings(
        provider=user_cfg.provider or sys_cfg.provider,
        base_url=user_cfg.base_url or sys_cfg.base_url,
        api_key=user_cfg.api_key or sys_cfg.api_key,
        chat_model=user_cfg.chat_model or sys_cfg.chat_model,
        timeout_seconds=user_cfg.timeout_seconds,
        max_retries=user_cfg.max_retries,
    )


def _build_langchain_model(cfg: LLMSettings) -> BaseChatModel:
    """构建 langchain ChatModel（OpenAI 兼容协议）。

    v2-M8.3: 导入 app.llm.minimax 触发 monkey-patch（在 langchain-openai ChatOpenAI 上注入 reasoning_content）
    """
    from langchain_openai import ChatOpenAI
    import app.llm.minimax  # noqa: F401  # 触发 monkey-patch

    model_name = cfg.chat_model.lower()
    is_minimax = model_name.startswith(("minimax", "abab"))

    kwargs: dict[str, Any] = {
        "model": cfg.chat_model,
        "api_key": cfg.api_key,
        "max_retries": cfg.max_retries,
        "timeout": cfg.timeout_seconds,
        "stream_usage": True,  # v2-M8.1: 让 stream 模式也在最后 chunk 带 usage_metadata
    }
    if cfg.base_url:
        kwargs["base_url"] = cfg.base_url
    if is_minimax:
        kwargs["extra_body"] = {"reasoning_split": True}
    return ChatOpenAI(**kwargs)


async def get_chat_model(
    db: AsyncSession | None = None,
    user_id: uuid.UUID | None = None,
) -> BaseChatModel:
    """主入口：返回 BaseChatModel。

    - LLM_MOCK=true 或 api_key 为空 → 返回 MockLLM
    - 否则按用户配置 / 系统配置加载
    """
    if is_mock_mode():
        return MockLLM()

    cfg: LLMSettings | None = None
    if db is not None and user_id is not None:
        user_cfg = await get_user_llm_settings(db, user_id)
        cfg = resolve_user_settings(user_cfg)
    else:
        cfg = SystemLLMConfig.from_settings().to_llm_settings()

    return _build_langchain_model(cfg)
