"""LLM 集成层：langchain + litellm 适配，支持 Mock。"""

from app.llm.factory import (
    LLMSettings,
    SystemLLMConfig,
    get_chat_model,
    get_user_llm_settings,
    resolve_user_settings,
)
from app.llm.mock import MockLLM, install_mock_mode

__all__ = [
    "LLMSettings",
    "SystemLLMConfig",
    "MockLLM",
    "get_chat_model",
    "get_user_llm_settings",
    "resolve_user_settings",
    "install_mock_mode",
]
