"""Chat 业务逻辑：chat_sessions CRUD + 调 LangGraph 主图。

阶段 6 增强：
- 多轮摘要（按 token 预算触发）
- thinking 持久化到 chat_messages.reasoning
- API 返回 memory_used + reasoning
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context_builder import (
    should_compress_session,
    summarize_messages,
)
from app.agents.graph import get_or_build_graph
from app.agents.state import new_state
from app.core.logging import get_logger
from app.db.models.chat import ChatMessage, ChatSession
from app.db.models.user import User
from app.llm.factory import is_mock_mode
from app.memory.time_context import format_natural

_logger = get_logger(__name__)


# ---------- 会话 CRUD ----------


async def create_session(db: AsyncSession, user_id: uuid.UUID, *, title: str = "") -> ChatSession:
    session = ChatSession(user_id=user_id, title=title)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def list_sessions(
    db: AsyncSession, user_id: uuid.UUID, *, limit: int = 50
) -> list[ChatSession]:
    stmt = (
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_session(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID
) -> ChatSession | None:
    stmt = select(ChatSession).where(ChatSession.user_id == user_id, ChatSession.id == session_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def delete_session(db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID) -> bool:
    session = await get_session(db, user_id, session_id)
    if session is None:
        return False
    await db.delete(session)
    await db.commit()
    return True


async def get_messages(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID, *, limit: int = 100
) -> list[ChatMessage]:
    session = await get_session(db, user_id, session_id)
    if session is None:
        return []
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


# ---------- 消息处理 ----------


async def send_message(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    content: str,
) -> dict[str, Any]:
    """发送用户消息，跑 LangGraph 主图，返回结构化结果。

    返回：
      {
        "trace_id": str,
        "user_message_id": str,
        "assistant_message_id": str,
        "final_response": str,
        "agents_invoked": list[str],
        "current_intent": str,
        "iterations": int,
        "memory_used": dict,   # 阶段 6 新增
        "compressed": bool,     # 是否做了多轮摘要
        "reasoning": str | None,  # 阶段 6 新增：thinking 单独字段
      }
    """
    # 1. 持久化用户消息
    user_msg = ChatMessage(session_id=session_id, role="user", content=content)
    db.add(user_msg)
    await db.flush()

    # 2. 构造 GraphState
    trace_id = uuid.uuid4().hex
    state = new_state(
        user_id=str(user_id),
        session_id=str(session_id),
        user_query=content,
        trace_id=trace_id,
    )

    # 3. 加载历史消息到 state
    history_limit = 20
    history = await get_messages(db, user_id, session_id, limit=history_limit)
    history_msgs: list = []
    for m in history:
        if m.role == "user":
            history_msgs.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            history_msgs.append(AIMessage(content=m.content))

    # 4. 阶段 6：多轮摘要（超 budget 时触发；v2-M1：按真实 token 计数）
    compressed = False
    summary_text = ""
    # 用用户的 token_budget 决定摘要触发阈值（v2-M1：基于真实 token）
    from app.agents.context_builder import SUMMARY_TRIGGER_TOKENS as _DEFAULT_TRIGGER_TOKENS

    user_row = await db.get(User, user_id)
    user_budget = user_row.token_budget if user_row else 8000
    # 缩放：默认 8000 token 对应 1500 trigger；按比例放大
    trigger_tokens = int(_DEFAULT_TRIGGER_TOKENS * user_budget / 8000)
    if should_compress_session(history_msgs, trigger_tokens=trigger_tokens, keep_recent=4):
        old = history_msgs[:-4]
        keep = history_msgs[-4:]
        try:
            from app.llm.factory import get_chat_model

            llm_for_summary = await get_chat_model(db=None, user_id=None)
            summary_text = await summarize_messages(llm_for_summary, old)
        except Exception as exc:
            _logger.warning("summary_fail", error=str(exc))
            summary_text = ""
        if summary_text:
            # 替换历史：1 条 SystemMessage 摘要 + 4 条最近
            history_msgs = [
                SystemMessage(content=f"[早期对话摘要]\n{summary_text}"),
                *keep,
            ]
            compressed = True
            _logger.info(
                "history_compressed",
                summary_chars=len(summary_text),
                trigger_tokens=trigger_tokens,
                user_budget=user_budget,
            )

    # 当前 user query 加到末尾
    state["messages"] = history_msgs + [HumanMessage(content=content)]

    # 5. 跑主图
    graph = await get_or_build_graph(str(user_id), str(session_id), force_mock=is_mock_mode())
    _logger.info(
        "chat_message_received",
        session=str(session_id),
        query=content[:80],
        history_count=len(history_msgs),
        compressed=compressed,
    )

    result = await graph.ainvoke(state)

    # 6. 解析返回：final_response + reasoning（thinking）
    final_response = result.get("final_response") or "（无回复）"
    next_agents = result.get("next_agents", [])
    current_intent = result.get("current_intent", "")

    # 抽取最后一条 AIMessage 的 reasoning_details
    reasoning = None
    messages_out = result.get("messages", [])
    for m in reversed(messages_out):
        if isinstance(m, AIMessage):
            additional = getattr(m, "additional_kwargs", {}) or {}
            reasoning = additional.get("reasoning_details")
            if reasoning:
                # reasoning 可能是 list[dict] 或 str
                if isinstance(reasoning, list):
                    reasoning = json.dumps(reasoning, ensure_ascii=False, default=str)
                break

    # 7. 持久化 AI 回复（含 reasoning）
    ai_msg = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=final_response,
        tool_calls=[{"agents": next_agents, "intent": current_intent}],
        reasoning=reasoning,
    )
    db.add(ai_msg)

    # 更新 session.updated_at
    session = await get_session(db, user_id, session_id)
    if session and not session.title:
        session.title = content[:30]
        session.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(ai_msg)

    # 8. fire-and-forget：persona 自主更新
    try:
        import asyncio

        from app.db.session import get_sessionmaker
        from app.services import persona_service

        _sm = get_sessionmaker()

        async def _persona_task():
            async with _sm() as _db:
                await persona_service.maybe_update_persona(_db, user_id, content, final_response)

        asyncio.create_task(_persona_task())
        _logger.info("persona_check_scheduled", user=str(user_id))
    except Exception as exc:
        _logger.warning("persona_schedule_fail", error=str(exc))

    _logger.info(
        "chat_message_done",
        session=str(session_id),
        agents=next_agents,
        response_len=len(final_response),
        compressed=compressed,
        has_reasoning=bool(reasoning),
    )

    return {
        "trace_id": trace_id,
        "user_message_id": str(user_msg.id),
        "assistant_message_id": str(ai_msg.id),
        "final_response": final_response,
        "agents_invoked": next_agents,
        "current_intent": current_intent,
        "iterations": result.get("iteration", 0),
        "memory_used": {
            "L1_session_loaded": len(history_msgs),
            "compressed": compressed,
            "summary_chars": len(summary_text) if summary_text else 0,
            "current_time": format_natural(),
        },
        "compressed": compressed,
        "reasoning": reasoning,
    }
