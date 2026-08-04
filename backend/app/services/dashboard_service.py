"""重点事件看板：聚合 events + topics + timeline。"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.memory import MemoryMediumTopic
from app.db.models.memory_event import MemoryEvent, MemoryEventTimeline

_logger = get_logger(__name__)


def _week_key(dt: datetime) -> str:
    """ISO 周 key: 2026-W31 格式。"""
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


async def build_dashboard(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    days: int = 30,
) -> dict[str, Any]:
    """构建看板数据：按周 / 按类型聚合事件 + 时间线 + 话题。"""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # 1. 事件
    events_stmt = (
        select(MemoryEvent)
        .where(
            MemoryEvent.user_id == user_id,
            MemoryEvent.created_at >= cutoff,
        )
        .order_by(MemoryEvent.created_at.desc())
    )
    events = list((await db.execute(events_stmt)).scalars().all())

    # 2. 话题
    topics_stmt = (
        select(MemoryMediumTopic)
        .where(MemoryMediumTopic.user_id == user_id, MemoryMediumTopic.created_at >= cutoff)
        .order_by(MemoryMediumTopic.created_at.desc())
    )
    topics = list((await db.execute(topics_stmt)).scalars().all())

    # 3. 按周聚合
    by_week: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        week = _week_key(e.created_at)
        by_week[week].append(
            {
                "event_id": str(e.id),
                "title": e.title,
                "summary": e.summary,
                "status": e.status,
                "confidence": e.confidence,
                "start_at": e.start_at.isoformat() if e.start_at else None,
                "end_at": e.end_at.isoformat() if e.end_at else None,
                "created_at": e.created_at.isoformat(),
            }
        )

    # 4. 按状态聚合
    by_status: dict[str, int] = defaultdict(int)
    for e in events:
        by_status[e.status] += 1

    # 5. 事件时间线（最新 10 个 event 的 timeline）
    timeline: list[dict] = []
    for e in events[:10]:
        tl_stmt = (
            select(MemoryEventTimeline)
            .where(MemoryEventTimeline.event_id == e.id)
            .order_by(MemoryEventTimeline.occurred_at.asc())
        )
        tl_rows = list((await db.execute(tl_stmt)).scalars().all())
        if tl_rows:
            timeline.append(
                {
                    "event_id": str(e.id),
                    "event_title": e.title,
                    "points": [
                        {
                            "occurred_at": t.occurred_at.isoformat(),
                            "event_type": t.event_type,
                            "content": t.content,
                        }
                        for t in tl_rows
                    ],
                }
            )

    # 6. 话题（最近 30 个）
    topic_items = [
        {
            "topic": t.topic,
            "summary": t.summary,
            "created_at": t.created_at.isoformat(),
        }
        for t in topics[:30]
    ]

    return {
        "days": days,
        "summary": {
            "total_events": len(events),
            "total_topics": len(topics),
            "by_status": dict(by_status),
        },
        "events_by_week": dict(by_week),
        "timeline": timeline,
        "topics": topic_items,
    }
