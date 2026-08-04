"""中期话题记忆：把每轮对话提炼为 1-N 个 topic，写入 memory_medium_topics（带向量）。

设计：
- 触发：chat_message_done 后异步触发（fire-and-forget）
- 输入：用户消息 + AI 回复 + current_time
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


TopicExtractOutput = list[TopicItem]


def _fallback_extract(user_msg: str, ai_msg: str) -> TopicExtractOutput:
    """LLM 不可用时的兜底：用用户消息前 30 字作为 topic。"""
    topic = user_msg[:30].strip() or "（未识别话题）"
    return [TopicItem(topic=topic, summary=f"用户：{user_msg[:80]}\n回复：{ai_msg[:80]}")]


async def extract_and_store_topics(
    db: AsyncSession,
    user_id: uuid.UUID,
    user_message: str,
    ai_message: str,
    *,
    current_time: str | None = None,
) -> int:
    """从单轮对话中提炼 topic 写入 memory_medium_topics。

    Returns: 新增 topic 数（失败 0）。
    """
    if not user_message.strip():
        return 0

    topics: TopicExtractOutput
    try:
        topics = await _call_llm_to_extract(user_message, ai_message)
    except Exception as exc:
        _logger.warning("topic_extract_llm_fail", error=str(exc))
        topics = _fallback_extract(user_message, ai_message)

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
        )
    except Exception as exc:
        await db.rollback()
        _logger.warning("topic_commit_fail", error=str(exc))
        return 0

    return len(topics)


async def _call_llm_to_extract(user_msg: str, ai_msg: str) -> TopicExtractOutput:
    """用 LLM 提炼 topic。"""
    from app.llm.factory import get_chat_model

    system_prompt = """你是话题提炼助手。从一段对话中提炼 1-3 个 topic，用于后期语义检索。

每个 topic：
- topic: 5-15 字的话题标题（中文优先）
- summary: 50-100 字摘要

返回严格 JSON 数组（不加任何说明文字）：
[{"topic": "...", "summary": "..."}, ...]"""

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
    return TopicExtractOutput.model_validate(data)


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
