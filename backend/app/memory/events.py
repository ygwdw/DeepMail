"""L3 事件记忆：events + event_timeline。

最小可用：
- 写：create_event + add_timeline + extract_events_from_topics（手动触发）
- 读：list_events + get_event
- 删：delete_event
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.memory_event import MemoryEvent, MemoryEventTimeline

_logger = get_logger(__name__)


# ---------- CRUD ----------


async def create_event(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    title: str,
    summary: str = "",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    status: str = "active",
    confidence: float = 1.0,
) -> MemoryEvent:
    now = datetime.now(UTC)
    event = MemoryEvent(
        user_id=user_id,
        title=title,
        summary=summary,
        status=status,
        confidence=confidence,
        start_at=start_at,
        end_at=end_at,
        created_at=now,
        updated_at=now,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    _logger.info("event_created", user=str(user_id), title=title[:50])
    return event


async def add_timeline(
    db: AsyncSession,
    event_id: uuid.UUID,
    *,
    occurred_at: datetime,
    event_type: str = "note",
    content: str = "",
    source_ref: str | None = None,
) -> MemoryEventTimeline:
    row = MemoryEventTimeline(
        event_id=event_id,
        occurred_at=occurred_at,
        event_type=event_type,
        content=content,
        source_ref=source_ref,
        created_at=datetime.now(UTC),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def list_events(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[MemoryEvent]:
    stmt = (
        select(MemoryEvent)
        .where(MemoryEvent.user_id == user_id)
        .order_by(MemoryEvent.created_at.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(MemoryEvent.status == status)
    return list((await db.execute(stmt)).scalars().all())


async def get_event(
    db: AsyncSession,
    user_id: uuid.UUID,
    event_id: uuid.UUID,
) -> MemoryEvent | None:
    stmt = select(MemoryEvent).where(MemoryEvent.user_id == user_id, MemoryEvent.id == event_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_event_timeline(
    db: AsyncSession,
    event_id: uuid.UUID,
) -> list[MemoryEventTimeline]:
    stmt = (
        select(MemoryEventTimeline)
        .where(MemoryEventTimeline.event_id == event_id)
        .order_by(MemoryEventTimeline.occurred_at.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def delete_event(db: AsyncSession, user_id: uuid.UUID, event_id: uuid.UUID) -> bool:
    event = await get_event(db, user_id, event_id)
    if event is None:
        return False
    await db.delete(event)
    await db.commit()
    return True


# ---------- 手动提炼 ----------


async def extract_events_from_topics(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    min_topics: int = 3,
    days: int = 7,
) -> list[MemoryEvent]:
    """把最近 N 天同一时间段内 ≥ min_topics 个相关 topic 合并为 1 个 event。

    MVP：所有最近 topic 简单合并为一个 event（不真做语义聚类）。
    """
    from app.memory.medium_term import list_topics

    topics = await list_topics(db, user_id, days=days)
    if len(topics) < min_topics:
        _logger.info(
            "event_extract_skip",
            user=str(user_id),
            topics=len(topics),
            need=min_topics,
        )
        return []

    # 合并：title 用第一个 topic；summary 用前 3 个 topic；时间线用每个 topic
    title = topics[0].topic
    summary = "\n".join(f"• {t.topic}：{t.summary}" for t in topics[:3])

    event = await create_event(
        db,
        user_id,
        title=title,
        summary=summary,
        start_at=topics[0].created_at,
        end_at=topics[-1].created_at,
        confidence=0.7,
    )
    for t in topics:
        await add_timeline(
            db,
            event.id,
            occurred_at=t.created_at,
            event_type="topic",
            content=f"{t.topic}：{t.summary}",
            source_ref=f"topic:{t.id}",
        )
    _logger.info("events_extracted", user=str(user_id), count=1)
    return [event]
