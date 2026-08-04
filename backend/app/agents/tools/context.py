"""Agent context：跨工具共享 user_id / session_id。"""

from __future__ import annotations

import contextvars

# 每个 GraphState 绑定一个 user_id 上下文
_user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "agent_user_id", default=None
)
_session_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "agent_session_id", default=None
)


def set_agent_context(*, user_id: str, session_id: str | None = None) -> None:
    _user_id_var.set(user_id)
    if session_id is not None:
        _session_id_var.set(session_id)


def get_current_user_id() -> str | None:
    return _user_id_var.get()


def get_current_session_id() -> str | None:
    return _session_id_var.get()


import contextlib


@contextlib.asynccontextmanager
async def agent_context(*, user_id: str, session_id: str | None = None):
    token_u = _user_id_var.set(user_id)
    token_s = _session_id_var.set(session_id) if session_id else None
    try:
        yield
    finally:
        _user_id_var.reset(token_u)
        if token_s is not None:
            _session_id_var.reset(token_s)
