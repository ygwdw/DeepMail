"""中期话题记忆：把每轮对话提炼为 1-N 个 topic，写入 memory_medium_topics（带向量）。

设计：
- 触发：chat_message_done 后异步触发（fire-and-forget）
- 输入：用户消息 + AI 回复 + current_time + 来源（email_id / chat_session_id）
- 输出：1-N 个 topic（短摘要），embedding 入库
- 检索：RAG 走同一 hybrid retriever 时可指定 partition=medium_term（自动展开所有 topic）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.memory import MemoryMediumTopic
from app.llm.embeddings import get_embedding_client

_logger = get_logger(__name__)


class TopicItem(BaseModel):
    topic: str = Field(
        min_length=2,
        max_length=100,
        description="话题标题（5-15 字）",
    )
    summary: str = Field(
        min_length=5,
        max_length=500,
        description="话题摘要（< 100 字）",
    )


class TopicExtractOutput(BaseModel):
    """v2-M4.1: wrapper class，让 with_structured_output 稳定识别。"""
    items: list[TopicItem] = Field(default_factory=list, description="话题列表")


# v2-P2: 纯问候/语气词/过短消息 → 不值得存 topic
_TRIVIAL_KEYWORDS = (
    "你好", "您好", "你好呀", "您好呀", "在吗", "在不在", "在的",
    "谢谢", "辛苦了", "感谢", "嗯", "哦", "好的", "好", "ok", "okay",
    "hi", "hello", "嗨", "哈喽", "再见", "拜拜", "晚安", "早安",
    "早上好", "中午好", "下午好", "晚上好", "没事", "没什么",
)


def _is_trivial_message(msg: str) -> bool:
    """v2-P2: 判断消息是否为问候/语气词/过短（无长期价值）。"""
    m = (msg or "").strip()
    if not m:
        return True
    if len(m) < 6:
        return True
    # 取第一句（按常见标点/空格切分），命中问候/语气词视为闲聊
    first_word = m
    for sep in ("，", ",", "。", "!", "！", "？", "?", " ", "~", "～"):
        idx = m.find(sep)
        if idx != -1:
            first_word = m[:idx]
            break
    return first_word in _TRIVIAL_KEYWORDS


def _fallback_extract(user_msg: str, ai_msg: str) -> TopicExtractOutput:
    """LLM 不可用时的兜底：仅对"有实质内容"的消息生成 topic，否则返回空（不存噪音）。"""
    if _is_trivial_message(user_msg):
        return TopicExtractOutput(items=[])
    topic = user_msg[:30].strip() or "（未识别话题）"
    return TopicExtractOutput(items=[
        TopicItem(topic=topic, summary=f"用户：{user_msg[:80]}\n回复：{ai_msg[:80]}"),
    ])


async def extract_and_store_topics(
    db: AsyncSession,
    user_id: uuid.UUID,
    user_message: str,
    ai_message: str,
    *,
    current_time: str | None = None,
    email_id: uuid.UUID | None = None,
    chat_session_id: uuid.UUID | None = None,
) -> int:
    """从单轮对话中提炼 topic 写入 memory_medium_topics。

    v2-M4.1: 支持来源追溯（email_id / chat_session_id），用于 L2→L3 聚类。

    Returns: 新增 topic 数（失败 0）。
    """
    if not user_message.strip():
        return 0
    # v2-P2: 纯问候/语气词/过短消息直接跳过（省 LLM 调用 + 避免噪音 topic）
    if _is_trivial_message(user_message):
        return 0

    output: TopicExtractOutput
    try:
        output = await _call_llm_to_extract(user_message, ai_message)
    except Exception as exc:
        _logger.warning("topic_extract_llm_fail", error=str(exc))
        output = _fallback_extract(user_message, ai_message)

    topics = output.items
    if not topics:
        return 0

    # 向量化（批量）
    embed_client = get_embedding_client()
    try:
        summaries = [f"{t.topic}：{t.summary}" for t in topics]
        embeddings = await embed_client.embed(summaries)
    except Exception as exc:
        _logger.warning("topic_embed_fail", error=str(exc))
        embeddings = [None] * len(topics)

    now = datetime.now(UTC)
    for topic, vec in zip(topics, embeddings):
        db.add(
            MemoryMediumTopic(
                user_id=user_id,
                topic=topic.topic,
                summary=topic.summary,
                embedding=vec,
                email_id=email_id,
                chat_session_id=chat_session_id,
                created_at=now,
            )
        )

    try:
        await db.commit()
        _logger.info(
            "topics_stored",
            user=str(user_id),
            count=len(topics),
            time=current_time or "n/a",
            email_id=str(email_id) if email_id else None,
            chat_session_id=str(chat_session_id) if chat_session_id else None,
        )
    except Exception as exc:
        await db.rollback()
        _logger.warning("topic_commit_fail", error=str(exc))
        return 0

    return len(topics)


async def _call_llm_to_extract(user_msg: str, ai_msg: str) -> TopicExtractOutput:
    """用 LLM 提炼 topic。"""
    from app.llm.factory import get_chat_model

    system_prompt = """你是话题提炼助手。从一段对话中判断是否提炼 topic，用于后期语义检索。

判断标准（v2-P2，宁缺毋滥）：
- 如果这段对话是问候、寒暄、闲聊、无实质信息量的内容（如"你好""在吗""今天天气怎么样""随便聊聊"），返回空数组 []
- 只有当对话包含**值得长期记住**的信息时才提取 1-3 个 topic，例如：计划/安排、任务、事实、个人偏好、决定、重要事件
- 宁可少提取，也不要为了提取而提取

每个 topic：
- topic: 5-15 字的话题标题（中文优先）
- summary: 50-100 字摘要

返回严格 JSON 数组（不加任何说明文字）：
[]  或  [{"topic": "...", "summary": "..."}, ...]"""

    user_prompt = f"""用户消息：{user_msg[:500]}

助手回复：{ai_msg[:500]}

请立即输出 JSON 数组："""

    llm = await get_chat_model(db=None, user_id=None)
    msg = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    import json as _json

    from app.memory.time_context import inject_time_to_prompt

    # 注入时间
    msg[0]["content"] = inject_time_to_prompt(msg[0]["content"])

    response = await llm.ainvoke(msg)
    text = response.content if isinstance(response.content, str) else str(response.content)

    # 提取 JSON 数组（兼容 ```json fence）
    import re

    text = re.sub(r"```(?:json)?\s*\n?(.*?)\n?```", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        text = text[start : end + 1]
    data = _json.loads(text)
    # v2-M4.1: 兼容裸 list 与 wrapper 两种形态
    if isinstance(data, dict) and "items" in data:
        return TopicExtractOutput.model_validate(data)
    if isinstance(data, list):
        return TopicExtractOutput(items=[TopicItem.model_validate(x) for x in data])
    raise ValueError(f"unexpected topic extract payload: {type(data)}")


async def list_topics(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    days: int = 30,
    limit: int = 50,
) -> list[MemoryMediumTopic]:
    """列出用户最近 N 天的 topic。"""
    from datetime import timedelta

    cutoff = datetime.now(UTC) - timedelta(days=days)
    stmt = (
        select(MemoryMediumTopic)
        .where(MemoryMediumTopic.user_id == user_id, MemoryMediumTopic.created_at >= cutoff)
        .order_by(MemoryMediumTopic.created_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_topics_by_email(
    db: AsyncSession,
    user_id: uuid.UUID,
    email_id: uuid.UUID,
) -> list[MemoryMediumTopic]:
    """v2-M4.1: 列出某邮件产生的 L2 topic（溯源）。"""
    stmt = (
        select(MemoryMediumTopic)
        .where(
            MemoryMediumTopic.user_id == user_id,
            MemoryMediumTopic.email_id == email_id,
        )
        .order_by(MemoryMediumTopic.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def delete_topic(db: AsyncSession, user_id: uuid.UUID, topic_id: uuid.UUID) -> bool:
    topic = (
        await db.execute(
            select(MemoryMediumTopic).where(
                MemoryMediumTopic.user_id == user_id,
                MemoryMediumTopic.id == topic_id,
            )
        )
    ).scalar_one_or_none()
    if topic is None:
        return False
    await db.delete(topic)
    await db.commit()
    return True


# ---------- v2-A1: L2 向量检索注入 ----------


async def search_topics_by_vector(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    *,
    top_k: int = 5,
    days: int = 30,
    min_similarity: float = 0.3,
) -> list[tuple[MemoryMediumTopic, float]]:
    """v2-A1: 用 query 向量检索用户最近 N 天的 L2 话题，返回 (topic, similarity)。

    相似度 < min_similarity 的 topic 过滤掉（宁缺毋滥，避免无关记忆注入 prompt）。
    失败（embedding 异常）时返回空列表，不抛异常。
    """
    from datetime import timedelta

    from sqlalchemy import func, text

    # 前置检查：用户无可检索 topic 时直接返回空，避免白打 embedding API
    cnt = (
        await db.execute(
            select(func.count())
            .select_from(MemoryMediumTopic)
            .where(
                MemoryMediumTopic.user_id == user_id,
                MemoryMediumTopic.embedding.isnot(None),
            )
        )
    ).scalar() or 0
    if cnt == 0:
        return []

    try:
        query_vec = await get_embedding_client().embed_one(query)
    except Exception as exc:
        _logger.warning("l2_query_embed_fail", error=str(exc))
        return []

    cutoff = datetime.now(UTC) - timedelta(days=days)
    qvec = "[" + ",".join(f"{x:.7f}" for x in query_vec) + "]"
    sql = text(
        """
        SELECT id, topic, summary, email_id, chat_session_id, created_at,
               1 - (embedding <=> :qvec) AS similarity
        FROM memory_medium_topics
        WHERE user_id = :user_id
          AND created_at >= :cutoff
          AND embedding IS NOT NULL
        ORDER BY embedding <=> :qvec
        LIMIT :top_k
        """
    )
    rows = (
        await db.execute(
            sql,
            {"user_id": str(user_id), "cutoff": cutoff, "qvec": qvec, "top_k": top_k},
        )
    ).mappings().all()

    results: list[tuple[MemoryMediumTopic, float]] = []
    for r in rows:
        sim = float(r["similarity"])
        if sim < min_similarity:
            continue
        topic = MemoryMediumTopic(
            id=r["id"],
            user_id=user_id,
            topic=r["topic"],
            summary=r["summary"] or "",
            email_id=r["email_id"],
            chat_session_id=r["chat_session_id"],
            created_at=r["created_at"],
        )
        results.append((topic, sim))
    return results


def topics_to_prompt_block(
    topics: list[tuple[MemoryMediumTopic, float]] | list[MemoryMediumTopic],
) -> str:
    """v2-A1: 把检索到的 L2 话题拼成 system prompt 块（总量 ≤800 字）。"""
    if not topics:
        return ""
    lines = ["## 相关历史话题"]
    used = 0
    for item in topics[:5]:
        if isinstance(item, tuple):
            topic, sim = item
        else:
            topic, sim = item, None
        src = "邮件" if topic.email_id else ("会话" if topic.chat_session_id else "记忆")
        date_str = topic.created_at.strftime("%Y-%m-%d") if topic.created_at else ""
        sim_part = f"，相似度 {sim:.2f}" if sim is not None else ""
        title = (topic.topic or "")[:50]
        summary = (topic.summary or "")[:80]
        line = f"- [{title}]（来源：{src} {date_str}{sim_part}）\n  {summary}"
        if used + len(line) > 800:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines)
