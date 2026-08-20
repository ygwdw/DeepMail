"""Chat 业务逻辑：chat_sessions CRUD + 调 LangGraph 主图。

阶段 6 增强：
- 多轮摘要（按 token 预算触发）
- thinking 持久化到 chat_messages.reasoning
- API 返回 memory_used + reasoning

v2-M8 增强：
- send_message_stream() async generator：SSE 流式输出
- 监听 graph.astream_events() 推送 thinking/tool/content 事件
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any, AsyncIterator

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


# ---------- 公共：准备会话（send_message + send_message_stream 共享） ----------


async def _prepare_chat(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    content: str,
    *,
    enable_l5: bool = False,
    enable_l5_partitions: list[str] | None = None,
) -> tuple[ChatMessage, list, bool, str, dict]:
    """准备消息：持久化 user + 加载历史 + 多轮摘要 → 返回 (user_msg, history_msgs, compressed, summary_text, state)。

    v2-M4.3: 支持 L5 挂载检索（仅 enable_l5=True 时注入 knowledge_service.search 结果）。
    send_message 和 send_message_stream 都用这段逻辑。
    """
    # 1. 持久化用户消息
    user_msg = ChatMessage(session_id=session_id, role="user", content=content)
    db.add(user_msg)
    await db.flush()

    # 2. 加载历史消息
    history_limit = 20
    history = await get_messages(db, user_id, session_id, limit=history_limit)
    history_msgs: list = []
    for m in history:
        if m.role == "user":
            history_msgs.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            # v2-M8.1：从 tool_calls[0].reasoning_details 回填到 additional_kwargs
            # 这样下一轮 LLM 调用能保留完整 reasoning（Interleaved Thinking 要求）
            add_kwargs: dict = {}
            tc = (m.tool_calls or [])
            if tc and isinstance(tc[0], dict):
                rd = tc[0].get("reasoning_details")
                if isinstance(rd, list) and rd:
                    add_kwargs["reasoning_details"] = rd
            history_msgs.append(AIMessage(content=m.content, additional_kwargs=add_kwargs))

    # 3. 多轮摘要（v2-M1：按真实 token）
    compressed = False
    summary_text = ""
    from app.agents.context_builder import SUMMARY_TRIGGER_TOKENS as _DEFAULT_TRIGGER_TOKENS

    user_row = await db.get(User, user_id)
    user_budget = user_row.token_budget if user_row else 8000
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

    # 4. 构造 GraphState
    trace_id = uuid.uuid4().hex
    state = new_state(
        user_id=str(user_id),
        session_id=str(session_id),
        user_query=content,
        trace_id=trace_id,
    )

    # v2-M4.2: 自动注入 L4 personas 到 system prompt（不阻塞主流程）
    try:
        from app.memory.long_term import personas_to_prompt_block, search_personas

        persona_rows = await search_personas(db, user_id, limit=20)
        persona_block_text = personas_to_prompt_block(persona_rows)
    except Exception as exc:
        _logger.warning("persona_block_load_fail", error=str(exc))
        persona_block_text = ""

    # v2-A1: L2 相关话题检索注入（对齐 persona 模式；相似度低于阈值不注入）
    l2_block_text = ""
    state["l2_topic_count"] = 0
    try:
        from app.core.config import get_settings as _get_settings
        from app.memory.medium_term import (
            search_topics_by_vector,
            topics_to_prompt_block,
        )

        _l2_settings = _get_settings()
        if _l2_settings.l2_retrieval_enabled:
            l2_topics = await search_topics_by_vector(
                db,
                user_id,
                content,
                top_k=_l2_settings.l2_top_k,
                min_similarity=_l2_settings.l2_min_similarity,
            )
            l2_block_text = topics_to_prompt_block(l2_topics)
            state["l2_topic_count"] = len(l2_topics)
            if l2_topics:
                _logger.info("l2_topics_injected", count=len(l2_topics))
    except Exception as exc:
        _logger.warning("l2_retrieval_fail", error=str(exc))
        l2_block_text = ""

    # v2-M4.3: L5 挂载检索（仅 enable_l5=True 时调用）
    l5_block_text = ""
    state["l5_injected"] = False
    state["l5_sources"] = []
    if enable_l5:
        try:
            from app.services.knowledge_service import search as kb_search

            # partitions 为空 → 检索所有非 inbox 分区（partition="*" 不存在）
            # 取用户的所有 partition，过滤掉 inbox（inbox 是邮件默认分区，不需要挂载）
            from sqlalchemy import distinct

            from app.db.models.knowledge import KnowledgeChunk

            partition_stmt = (
                select(distinct(KnowledgeChunk.partition))
                .where(KnowledgeChunk.user_id == user_id)
            )
            all_partitions = [
                row[0]
                for row in (await db.execute(partition_stmt)).all()
                if row[0] != "inbox"
            ]
            target_partitions = [
                p for p in all_partitions
                if not enable_l5_partitions or p in enable_l5_partitions
            ]
            if target_partitions:
                hits = await kb_search(
                    db,
                    user_id=user_id,
                    query=content,
                    partitions=target_partitions,
                    top_k=5,
                )
                if hits:
                    lines = ["## 外部知识库检索结果（v2-M4.3 挂载）"]
                    sources: list[dict[str, Any]] = []
                    for h in hits[:5]:
                        # 溯源标签：[partition / source / filename or email subject]
                        meta = h.get("metadata", {}) or {}
                        filename = meta.get("filename") or meta.get("subject") or "未知"
                        src = h.get("source") or "unknown"
                        partition = h.get("partition") or "default"
                        lines.append(
                            f"- [{partition} / {src} / {filename}] {h['content'][:300]}"
                        )
                        sources.append(
                            {
                                "partition": partition,
                                "source": src,
                                "filename": filename,
                                "score": h.get("score"),
                                "chunk_id": str(h.get("chunk_id", "")),
                            }
                        )
                    l5_block_text = "\n".join(lines)
                    state["l5_sources"] = sources
                    state["l5_injected"] = True
        except Exception as exc:
            _logger.warning("l5_retrieval_fail", error=str(exc))
            l5_block_text = ""

    state["messages"] = history_msgs + [HumanMessage(content=content)]
    # 把 persona / l5 / l2 block 单独存进 state，供 assemble_system_prompt / tools 读取
    state["persona_block"] = persona_block_text
    state["l5_block"] = l5_block_text
    state["l2_block"] = l2_block_text
    # v2-M4.2 / v2-A1: 把 persona / l5 / l2 block 插到 messages 列表头部（SystemMessage）
    # entity_relation 不注入；它只能通过工具查询
    sys_msgs: list = []
    if persona_block_text:
        sys_msgs.append(SystemMessage(content=persona_block_text))
    if l2_block_text:
        sys_msgs.append(SystemMessage(content=l2_block_text))
    if l5_block_text:
        sys_msgs.append(SystemMessage(content=l5_block_text))
    if sys_msgs:
        state["messages"] = sys_msgs + state["messages"]
    return user_msg, history_msgs, compressed, summary_text, state


def _estimate_tokens(history_msgs: list, content_text: str) -> int:
    """估算 token 消耗（mock 模式）：用字符数 / 4 粗略估算（中文 ~1.5 char/token）。"""
    total = 0
    for m in history_msgs:
        c = getattr(m, "content", None)
        if isinstance(c, str):
            total += len(c)
        add = getattr(m, "additional_kwargs", None) or {}
        if isinstance(add, dict):
            for v in add.values():
                if isinstance(v, str):
                    total += len(v)
    if content_text:
        total += len(content_text)
    # 加上 thinking + tools 估计
    return max(total // 4, 1)


def _fire_and_forget_persona(user_id: uuid.UUID, user_msg: str, final_response: str) -> None:
    """fire-and-forget: 异步触发 persona 自主更新。"""
    try:
        import asyncio

        from app.db.session import get_sessionmaker
        from app.services import persona_service

        _sm = get_sessionmaker()

        async def _persona_task():
            async with _sm() as _db:
                await persona_service.maybe_update_persona(_db, user_id, user_msg, final_response)

        asyncio.create_task(_persona_task())
    except Exception as exc:
        _logger.warning("persona_schedule_fail", error=str(exc))


def _fire_and_forget_topics(
    user_id: uuid.UUID,
    user_msg: str,
    ai_msg: str,
    *,
    email_id: uuid.UUID | None = None,
    chat_session_id: uuid.UUID | None = None,
) -> None:
    """v2-M4.1: fire-and-forget 触发 L2 topic 提取（来源追溯 email_id / chat_session_id）。"""
    try:
        import asyncio

        from app.db.session import get_sessionmaker
        from app.memory.medium_term import extract_and_store_topics

        _sm = get_sessionmaker()

        async def _topic_task():
            async with _sm() as _db:
                await extract_and_store_topics(
                    _db,
                    user_id,
                    user_msg,
                    ai_msg,
                    email_id=email_id,
                    chat_session_id=chat_session_id,
                )

        asyncio.create_task(_topic_task())
    except Exception as exc:
        _logger.warning("topic_schedule_fail", error=str(exc))


def _fire_and_forget_long_term(user_id: uuid.UUID, user_msg: str, ai_msg: str) -> None:
    """v2-M4.2: fire-and-forget 触发 L4 long_term 提炼（user persona / entity_relation）。"""
    try:
        import asyncio

        from app.db.session import get_sessionmaker
        from app.memory.long_term import extract_long_term_from_conversation

        _sm = get_sessionmaker()

        async def _long_term_task():
            async with _sm() as _db:
                await extract_long_term_from_conversation(_db, user_id, user_msg, ai_msg)

        asyncio.create_task(_long_term_task())
    except Exception as exc:
        _logger.warning("long_term_schedule_fail", error=str(exc))


# ---------- 同步消息（向后兼容） ----------


async def send_message(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    content: str,
    *,
    enable_l5: bool = False,
    enable_l5_partitions: list[str] | None = None,
) -> dict[str, Any]:
    """发送用户消息，跑 LangGraph 主图，返回结构化结果（v2-M8 之前版本保留）。

    v2-M4.3: enable_l5 控制是否检索外部知识库并注入 system prompt。
    """
    user_msg, history_msgs, compressed, summary_text, state = await _prepare_chat(
        db,
        user_id,
        session_id,
        content,
        enable_l5=enable_l5,
        enable_l5_partitions=enable_l5_partitions,
    )

    graph = await get_or_build_graph(str(user_id), str(session_id), force_mock=is_mock_mode())
    _logger.info(
        "chat_message_received",
        session=str(session_id),
        query=content[:80],
        history_count=len(history_msgs),
        compressed=compressed,
    )

    result = await graph.ainvoke(state)

    final_response = result.get("final_response") or "（无回复）"
    next_agents = result.get("next_agents", [])
    current_intent = result.get("current_intent", "")

    reasoning = None
    messages_out = result.get("messages", [])
    for m in reversed(messages_out):
        if isinstance(m, AIMessage):
            additional = getattr(m, "additional_kwargs", {}) or {}
            reasoning = additional.get("reasoning_details")
            if reasoning:
                if isinstance(reasoning, list):
                    reasoning = json.dumps(reasoning, ensure_ascii=False, default=str)
                break

    ai_msg = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=final_response,
        tool_calls=[{"agents": next_agents, "intent": current_intent, "reasoning_details": reasoning if isinstance(reasoning, list) else None}],
        reasoning=reasoning,
    )
    db.add(ai_msg)

    session = await get_session(db, user_id, session_id)
    if session and not session.title:
        session.title = content[:30]
        session.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(ai_msg)

    _fire_and_forget_persona(user_id, content, final_response)
    # v2-M4.1: 异步触发 L2 topic 提取（chat 来源）
    _fire_and_forget_topics(user_id, content, final_response, chat_session_id=session_id)
    # v2-M4.2: 异步触发 L4 long_term 提炼（user persona / entity_relation）
    _fire_and_forget_long_term(user_id, content, final_response)

    _logger.info(
        "chat_message_done",
        session=str(session_id),
        agents=next_agents,
        response_len=len(final_response),
        compressed=compressed,
        has_reasoning=bool(reasoning),
    )

    return {
        "trace_id": state.get("trace_id"),
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


# ---------- v2-M8：流式消息（SSE） ----------


async def send_message_stream(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    content: str,
    *,
    enable_l5: bool = False,
    enable_l5_partitions: list[str] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """流式发送：监听 graph.astream_events()，yield 增量事件。

    事件类型：
      - user           ：用户消息回显（立即）
      - thinking       ：reasoning_details 增量（流）
      - tool_start     ：工具调用开始（name + args）
      - tool_end       ：工具调用结束（name + summary）
      - content        ：主文本增量（流）
      - l5_sources     ：v2-M4.3 L5 检索溯源（partition/source/filename/score）
      - usage          ：最终统计（duration_ms / iterations / tools_called）
      - error          ：错误
      - end            ：流结束
    """
    user_msg, history_msgs, compressed, summary_text, state = await _prepare_chat(
        db,
        user_id,
        session_id,
        content,
        enable_l5=enable_l5,
        enable_l5_partitions=enable_l5_partitions,
    )

    # v2-M4.3: 把 L5 溯源 yield 给前端（让前端能展示挂载来源）
    if state.get("l5_sources"):
        yield {
            "type": "l5_sources",
            "sources": state["l5_sources"],
        }

    yield {
        "type": "user",
        "content": content,
        "user_message_id": str(user_msg.id),
    }

    graph = await get_or_build_graph(str(user_id), str(session_id), force_mock=is_mock_mode())
    _logger.info(
        "chat_message_stream_start",
        session=str(session_id),
        query=content[:80],
        history_count=len(history_msgs),
        compressed=compressed,
    )

    start = time.time()
    tool_count = 0
    content_text = ""
    reasoning_text = ""
    reasoning_details_list: list = []  # v2-M8.1: 结构化 reasoning_details（用于 Interleaved Thinking 回填）
    next_agents: list[str] = []
    error_occurred = False
    final_response_emitted = False  # 防止多次 yield final_response
    total_input_tokens = 0
    total_output_tokens = 0
    total_tokens = 0

    # v2-M8.2: sub-agent 是 LangGraph node（不是 LC tool），所以 on_tool_start 不触发
    # 把 sub-agent 节点的 on_chain_start/end 转成 tool_start/tool_end 事件，让前端能展示
    SUB_AGENT_NODE_NAMES = {"email_agent", "todo_agent", "draft_agent", "rag_agent", "tidy_agent"}
    sub_agent_start_time: dict[str, float] = {}
    # v2-M8.8: 工具调用历史（用于持久化，让前端刷新后仍能看到工具卡片）
    persisted_tools: list[dict] = []

    # v2-M8.3: aggregator / chat 节点 phase 标记。on_chain_start(name=aggregator|chat) 开始 → 直到 on_chain_end
    # 期间所有 on_chat_model_stream 的 content 都 yield 给前端（流式正文）
    in_aggregator_phase = False
    # v2-M8.11: 当前 LangGraph node 名称（用于 thinking 分段）
    current_node_name: str = "supervisor"
    # 已知业务节点（避免 sub-agent 内部 chat_model 也开新框）；v2-P2 加 chat 直聊节点
    KNOWN_NODES = {"supervisor", "email_agent", "todo_agent", "draft_agent", "rag_agent", "tidy_agent", "aggregator", "chat"}

    try:
        async for event in graph.astream_events(state, version="v2"):
            kind = event.get("event", "")
            name = event.get("name", "")
            data = event.get("data", {}) or {}

            if kind == "on_chain_start" and name in SUB_AGENT_NODE_NAMES:
                # sub-agent 开始 → 当作"工具调用"开始
                current_node_name = name  # v2-M8.11: 切到 sub-agent，thinking 段更新
                sub_agent_start_time[name] = time.time()
                tool_count += 1
                persisted_tools.append({"name": name, "status": "running", "args_summary": "(sub-agent dispatched)"})
                yield {
                    "type": "tool_start",
                    "name": name,
                    "args_summary": "(sub-agent dispatched)",
                }
                continue

            if kind == "on_chain_start" and name in ("aggregator", "chat"):
                # v2-M8.3: aggregator / chat 进入 phase → 后续 chat_model_stream 的 content 都 yield 流式正文
                current_node_name = name  # v2-M8.11 / v2-P2
                in_aggregator_phase = True
                continue

            if kind == "on_chain_start" and name == "supervisor":
                # v2-M8.11: supervisor 节点
                current_node_name = "supervisor"
                continue

            if kind == "on_chain_end" and name in SUB_AGENT_NODE_NAMES:
                # sub-agent 结束 → 当作"工具调用"结束
                dur_ms = 0
                if name in sub_agent_start_time:
                    dur_ms = int((time.time() - sub_agent_start_time[name]) * 1000)
                    del sub_agent_start_time[name]
                out = data.get("output") or {}
                # 取最后一条 AI message 的 content 作为 summary
                summary = ""
                if isinstance(out, dict):
                    msgs = out.get("messages") or []
                    for m in reversed(msgs):
                        if isinstance(m, AIMessage) and m.content:
                            summary = (str(m.content) or "")[:200]
                            break
                # v2-M8.8: 更新 persisted_tools（找最后一个 running 的同名工具）
                updated = False
                for i in range(len(persisted_tools) - 1, -1, -1):
                    if persisted_tools[i].get("name") == name and persisted_tools[i].get("status") == "running":
                        persisted_tools[i] = {
                            "name": name,
                            "status": "done",
                            "summary": summary,
                            "duration_ms": dur_ms,
                        }
                        updated = True
                        break
                if not updated:
                    persisted_tools.append({
                        "name": name, "status": "done", "summary": summary, "duration_ms": dur_ms,
                    })
                yield {
                    "type": "tool_end",
                    "name": name,
                    "summary": summary,
                    "duration_ms": dur_ms,
                }
                continue

            if kind == "on_chat_model_stream":
                chunk = data.get("chunk")
                if not isinstance(chunk, AIMessage):
                    continue
                # reasoning 增量（任何节点都累积 thinking）
                ak = chunk.additional_kwargs or {}
                # v2-M8.3: 优先 reasoning_content（MiniMax-M3 流式友好格式），fallback reasoning_details
                rc_text = ak.get("reasoning_content") or ""
                rd = ak.get("reasoning_details")
                if rc_text or rd:
                    thinking_delta = rc_text
                    if not thinking_delta and rd:
                        thinking_delta = json.dumps(rd, ensure_ascii=False, default=str)
                    if thinking_delta:
                        reasoning_text += thinking_delta
                        # v2-M8.1: 累积结构化 reasoning_details（用于 Interleaved Thinking 持久化）
                        if isinstance(rd, list):
                            reasoning_details_list.extend(rd)
                        elif rd and not rc_text:
                            reasoning_details_list.append(rd)
                        # v2-M8.11: 携带触发该 reasoning 的 LangGraph node name
                        # 让前端可以按节点分段显示（避免 supervisor + sub-agent + aggregator 累积到同一框）
                        # 用 event name (LangGraph node 名)；name 在 chain_start 钩子维护
                        yield {"type": "thinking", "delta": thinking_delta, "name": current_node_name}
                # v2-M8.3: 正文 content 流式 — 只 yield aggregator phase 内的 chunk
                # 用 on_chain_start(name=aggregator) / on_chain_end(name=aggregator) 切 phase
                # （langchain chat_model 事件 tags 不继承父 node 标签，只能用 phase 标记）
                if in_aggregator_phase and chunk.content:
                    content_text += chunk.content
                    yield {"type": "content", "delta": chunk.content}

            elif kind == "on_chat_model_end":
                # v2-M8.1：从 AIMessage.usage_metadata 累加真实 token（mock + 真实 LLM 都填）
                output_msg = data.get("output")
                if isinstance(output_msg, AIMessage):
                    um = getattr(output_msg, "usage_metadata", None)
                    if isinstance(um, dict):
                        total_input_tokens += int(um.get("input_tokens") or 0)
                        total_output_tokens += int(um.get("output_tokens") or 0)
                        total_tokens += int(um.get("total_tokens") or 0)

            elif kind == "on_tool_start":
                # v2-M8.2: sub-agent 内部工具事件 → 只暴露，不计入 tool_count（避免双层卡片）
                # 因为 sub-agent 节点本身已经作为 tool 卡片展示了
                args = data.get("input", {}) or {}
                args_summary = json.dumps(args, ensure_ascii=False, default=str)[:200]
                # v2-M8.8: 持久化（前端刷新后仍能看到工具卡片）
                persisted_tools.append({
                    "name": name or "tool",
                    "status": "running",
                    "args_summary": args_summary,
                })
                yield {
                    "type": "tool_start",
                    "name": name or "tool",
                    "args_summary": args_summary,
                }

            elif kind == "on_tool_end":
                output = data.get("output")
                output_summary = str(output)[:200] if output is not None else ""
                # 更新 persisted_tools 中对应记录
                updated = False
                for i in range(len(persisted_tools) - 1, -1, -1):
                    if persisted_tools[i].get("name") == (name or "tool") and persisted_tools[i].get("status") == "running":
                        persisted_tools[i] = {
                            "name": name or "tool",
                            "status": "done",
                            "summary": output_summary,
                        }
                        updated = True
                        break
                if not updated:
                    persisted_tools.append({
                        "name": name or "tool", "status": "done", "summary": output_summary,
                    })
                yield {
                    "type": "tool_end",
                    "name": name or "tool",
                    "summary": output_summary,
                }

            elif kind == "on_chain_end":
                output = data.get("output") or {}
                if isinstance(output, dict):
                    na = output.get("next_agents")
                    if isinstance(na, list):
                        next_agents = na
                    # v2-M8 修复：只在 aggregator / chat 节点结束时推送 final_response
                    # 避免 Supervisor + sub-agent + Aggregator 三个节点的中间内容重复显示
                    if name in ("aggregator", "chat"):  # v2-P2: chat 直聊节点同样收尾
                        in_aggregator_phase = False  # v2-M8.3: 退出 phase
                        if not final_response_emitted:
                            fr = output.get("final_response")
                            if fr:
                                content_text = fr
                                yield {"type": "content_replace", "text": fr}
                            final_response_emitted = True
    except Exception as exc:
        _logger.exception("chat_message_stream_fail", session=str(session_id), error=str(exc))
        error_occurred = True
        yield {"type": "error", "message": str(exc)}

    duration_ms = int((time.time() - start) * 1000)

    # 持久化 AI 回复
    final_response = content_text or "（无回复）"
    # v2-M8.8: 持久化 thinking/tools/stats 给前端刷新后展示
    persisted_tc: dict = {
        "agents": next_agents,
        "thinking": reasoning_text or "",
        "tools": persisted_tools,
        "stats": {
            "duration_ms": duration_ms,
            "iterations": 1,
            "tools_called": tool_count,
            "tokens": total_tokens,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
        },
    }
    # v2-M8.1: reasoning_details 必须完整保留（Interleaved Thinking 链不断）
    if reasoning_details_list:
        persisted_tc["reasoning_details"] = reasoning_details_list
    ai_msg = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=final_response,
        tool_calls=[persisted_tc],
        tokens_used=total_tokens,
        reasoning=reasoning_text or None,
    )
    db.add(ai_msg)
    session = await get_session(db, user_id, session_id)
    if session and not session.title:
        session.title = content[:30]
        session.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(ai_msg)

    _fire_and_forget_persona(user_id, content, final_response)
    # v2-M4.1: 异步触发 L2 topic 提取（chat 来源）
    _fire_and_forget_topics(user_id, content, final_response, chat_session_id=session_id)
    # v2-M4.2: 异步触发 L4 long_term 提炼（user persona / entity_relation）
    _fire_and_forget_long_term(user_id, content, final_response)

    _logger.info(
        "chat_message_stream_done",
        session=str(session_id),
        agents=next_agents,
        response_len=len(final_response),
        duration_ms=duration_ms,
        tool_count=tool_count,
        error=error_occurred,
    )

    yield {
        "type": "usage",
        "duration_ms": duration_ms,
        "iterations": 1,
        "tools_called": tool_count,
        "agents_invoked": next_agents,
        "compressed": compressed,
        "tokens": total_tokens or _estimate_tokens(history_msgs, content_text),  # fallback 防止 mock 旧版本漏填
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "assistant_message_id": str(ai_msg.id),
        "final_response": final_response,
    }
    yield {"type": "end"}
