"""全局结构化日志（structlog）。

特点：
- JSON / 控制台双格式
- trace_id / span_id 上下文传播
- 自动加 timestamp / level / logger
- 异步安全（contextvars）
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

from app.core.config import get_settings

# 上下文变量：trace_id / span_id / user_id 等
_trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
_span_id_var: ContextVar[str | None] = ContextVar("span_id", default=None)
_user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
_session_id_var: ContextVar[str | None] = ContextVar("session_id", default=None)


# ---------- 上下文工具 ----------


def set_trace_id(trace_id: str | None) -> None:
    _trace_id_var.set(trace_id)


def get_trace_id() -> str | None:
    return _trace_id_var.get()


def set_span_id(span_id: str | None) -> None:
    _span_id_var.set(span_id)


def set_user_context(user_id: str | None = None, session_id: str | None = None) -> None:
    if user_id is not None:
        _user_id_var.set(user_id)
    if session_id is not None:
        _session_id_var.set(session_id)


def _inject_context(_logger: Any, _name: str, event_dict: dict) -> dict:
    """structlog processor：注入 contextvar 中的 trace_id / span_id / user。"""
    tid = _trace_id_var.get()
    sid = _span_id_var.get()
    uid = _user_id_var.get()
    sess = _session_id_var.get()
    if tid:
        event_dict.setdefault("trace_id", tid)
    if sid:
        event_dict.setdefault("span_id", sid)
    if uid:
        event_dict.setdefault("user_id", uid)
    if sess:
        event_dict.setdefault("session_id", sess)
    return event_dict


# ---------- 初始化 ----------

_CONFIGURED = False


def configure_logging() -> None:
    """全局日志初始化（幂等）。"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # 把 stdlib logging 桥接到 structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    # 选择渲染器：开发用 console，生产用 JSON
    if settings.app_debug:
        renderer = structlog.dev.ConsoleRenderer(colors=False)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _inject_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    configure_logging()
    return structlog.get_logger(name) if name else structlog.get_logger()


# ---------- 上下文管理器 ----------

import contextlib
import uuid


@contextlib.contextmanager
def trace_context(trace_id: str | None = None, **kwargs: Any):
    """trace 上下文管理器：with trace_context(trace_id=...) as t: ... 结束时清理。"""
    tid = trace_id or uuid.uuid4().hex
    set_trace_id(tid)
    set_user_context(**kwargs)
    try:
        yield tid
    finally:
        set_trace_id(None)
        set_user_context(None, None)


@contextlib.contextmanager
def span_context(span_id: str | None = None):
    sid = span_id or uuid.uuid4().hex[:16]
    set_span_id(sid)
    try:
        yield sid
    finally:
        set_span_id(None)
