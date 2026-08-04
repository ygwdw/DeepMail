"""LangGraph GraphState 定义。"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from langgraph.graph import add_messages
from typing_extensions import TypedDict


class GraphState(TypedDict, total=False):
    """多 Agent 编排的主状态。"""

    # 会话 / 用户维度
    user_id: str
    session_id: str
    trace_id: str

    # 当前时间上下文（自然语言格式 + ISO）
    current_time: str  # "2026-08-04 10:30 星期二"
    current_time_iso: str  # "2026-08-04T10:30:00+08:00"

    # 消息历史（langgraph reducer 自动合并）
    messages: Annotated[list, add_messages]

    # Supervisor 路由
    current_intent: str
    next_agents: list[str]  # 由 supervisor 决定派发哪些 sub-agent
    # 用户原始 query（supervisor 输入）
    user_query: str

    # 计数 / 限流
    iteration: int
    tool_calls_count: int
    total_tokens: int

    # sub-agent 中间结果（协同用）
    intermediate_outputs: dict[str, Any]

    # 最终回复
    final_response: str
    error: str | None


def new_state(
    user_id: str,
    session_id: str,
    user_query: str,
    *,
    trace_id: str | None = None,
) -> GraphState:
    """构造初始 state。"""
    from app.memory.time_context import format_iso, format_natural

    return GraphState(
        user_id=user_id,
        session_id=session_id,
        trace_id=trace_id or uuid.uuid4().hex,
        current_time=format_natural(),
        current_time_iso=format_iso(),
        user_query=user_query,
        messages=[],
        iteration=0,
        tool_calls_count=0,
        total_tokens=0,
        intermediate_outputs={},
    )
