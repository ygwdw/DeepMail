"""/api/memory/* 路由。"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.memory import events, long_term, medium_term
from app.schemas.common import ORMModel

router = APIRouter(prefix="/api/memory", tags=["memory"])


# ---------- Schemas ----------


class TopicRead(ORMModel):
    id: uuid.UUID
    topic: str
    summary: str
    created_at: datetime


class LongTermRead(ORMModel):
    id: uuid.UUID
    key: str
    value: dict
    importance: float
    decay_score: float
    category: str
    updated_at: datetime


class EventRead(ORMModel):
    id: uuid.UUID
    title: str
    summary: str
    status: str
    confidence: float
    start_at: datetime | None
    end_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TimelineRead(ORMModel):
    id: uuid.UUID
    occurred_at: datetime
    event_type: str
    content: str
    source_ref: str | None


class EventDetailRead(EventRead):
    timeline: list[TimelineRead]


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    summary: str = ""
    start_at: datetime | None = None
    end_at: datetime | None = None


# ---------- L2 话题 ----------


@router.get("/topics", response_model=list[TopicRead])
async def list_topics(
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TopicRead]:
    rows = await medium_term.list_topics(db, current.id, days=days, limit=limit)
    return [
        TopicRead(id=r.id, topic=r.topic, summary=r.summary, created_at=r.created_at) for r in rows
    ]


@router.delete("/topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_topic(
    topic_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    ok = await medium_term.delete_topic(db, current.id, topic_id)
    if not ok:
        raise HTTPException(status_code=404, detail="topic not found")


# ---------- L3 事件 ----------


@router.get("/events", response_model=list[EventRead])
async def list_events(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EventRead]:
    rows = await events.list_events(db, current.id, status=status_filter, limit=limit)
    return [
        EventRead(
            id=r.id,
            title=r.title,
            summary=r.summary,
            status=r.status,
            confidence=r.confidence,
            start_at=r.start_at,
            end_at=r.end_at,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.get("/events/{event_id}", response_model=EventDetailRead)
async def get_event(
    event_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventDetailRead:
    event = await events.get_event(db, current.id, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    timeline = await events.get_event_timeline(db, event_id)
    return EventDetailRead(
        id=event.id,
        title=event.title,
        summary=event.summary,
        status=event.status,
        confidence=event.confidence,
        start_at=event.start_at,
        end_at=event.end_at,
        created_at=event.created_at,
        updated_at=event.updated_at,
        timeline=[
            TimelineRead(
                id=t.id,
                occurred_at=t.occurred_at,
                event_type=t.event_type,
                content=t.content,
                source_ref=t.source_ref,
            )
            for t in timeline
        ],
    )


@router.post("/events", response_model=EventRead, status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: EventCreate,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventRead:
    event = await events.create_event(
        db,
        current.id,
        title=payload.title,
        summary=payload.summary,
        start_at=payload.start_at,
        end_at=payload.end_at,
    )
    return EventRead(
        id=event.id,
        title=event.title,
        summary=event.summary,
        status=event.status,
        confidence=event.confidence,
        start_at=event.start_at,
        end_at=event.end_at,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    ok = await events.delete_event(db, current.id, event_id)
    if not ok:
        raise HTTPException(status_code=404, detail="event not found")


@router.post("/events/extract", response_model=list[EventRead])
async def extract_events(
    days: int = Query(default=7, ge=1, le=30),
    min_topics: int = Query(default=3, ge=2, le=10),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EventRead]:
    """手动触发：把最近 N 天的话题聚合成事件。"""
    rows = await events.extract_events_from_topics(db, current.id, min_topics=min_topics, days=days)
    return [
        EventRead(
            id=r.id,
            title=r.title,
            summary=r.summary,
            status=r.status,
            confidence=r.confidence,
            start_at=r.start_at,
            end_at=r.end_at,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


# ---------- L4 长期记忆 ----------


@router.get("/long-term", response_model=list[LongTermRead])
async def list_long_term(
    category: str | None = Query(default=None),
    min_decay: float = Query(default=0.1, ge=0.0, le=1.0),
    limit: int = Query(default=50, ge=1, le=200),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LongTermRead]:
    rows = await long_term.list_long_term(
        db, current.id, category=category, min_decay=min_decay, limit=limit
    )
    return [
        LongTermRead(
            id=r.id,
            key=r.key,
            value=r.value,
            importance=r.importance,
            decay_score=r.decay_score,
            category=r.category,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.post("/long-term/decay")
async def run_decay(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """跑一次衰减更新（每个用户的 memory_long_term.decay_score 重新计算）。"""
    n = await long_term.run_decay_update(db, current.id)
    return {"updated": n}


@router.delete("/long-term/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_long_term(
    key: str,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    ok = await long_term.delete_long_term(db, current.id, key)
    if not ok:
        raise HTTPException(status_code=404, detail="key not found")
