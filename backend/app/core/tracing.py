"""langsmith 集成。

工作原理：
- 设置环境变量 LANGSMITH_TRACING=true + LANGSMITH_API_KEY + LANGSMITH_PROJECT
- langchain / langgraph 自动把每次 LLM call / tool call / agent run 写到 langsmith
- 通过 LANGSMITH_ENDPOINT 可指向自部署

不开启时（默认）：
- langsmith 是 no-op
- 我们的应用仍用 structlog 输出本地日志
- trace_id 通过 contextvars 透传到 structlog
"""

from __future__ import annotations

import os

from app.core.config import get_settings
from app.core.logging import get_logger

_logger = get_logger(__name__)


def configure_langsmith() -> bool:
    """配置 langsmith 环境变量。返回是否启用。"""
    settings = get_settings()
    api_key = os.getenv("LANGSMITH_API_KEY") or settings.langsmith_api_key
    project = os.getenv("LANGSMITH_PROJECT") or settings.langsmith_project
    endpoint = os.getenv("LANGSMITH_ENDPOINT") or settings.langsmith_endpoint
    # v2-P2: 兼容 .env 的 LANGSMITH_TRACING=true（pydantic-settings 读到 langsmith_tracing）
    enabled_env = (
        os.getenv("LANGSMITH_TRACING", "").lower() in ("1", "true", "yes")
        or settings.langsmith_tracing
    )

    if not (api_key and enabled_env):
        _logger.info("langsmith_disabled", reason="no API key or LANGSMITH_TRACING not set")
        return False

    # langsmith 启用
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGSMITH_PROJECT"] = project or "deepmail"
    if endpoint:
        os.environ["LANGSMITH_ENDPOINT"] = endpoint

    _logger.info(
        "langsmith_enabled",
        project=os.environ["LANGSMITH_PROJECT"],
        endpoint=endpoint or "(default)",
    )
    return True


# 是否启用（启动时检测一次）
_LANGSMITH_ENABLED = configure_langsmith()


def is_langsmith_enabled() -> bool:
    return _LANGSMITH_ENABLED


def get_langsmith_client():
    """返回 langsmith Client（用于主动查询 trace）。"""
    from langsmith import Client

    return Client()
