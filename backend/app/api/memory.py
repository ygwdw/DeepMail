"""/api/memory/* 路由。"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
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


# ---------- v2-M4.2: personas + relations 专属端点 ----------


class PersonaUpsert(BaseModel):
    key: str = Field(min_length=1, max_length=128, description="画像键名，如 user_name / user_role")
    text: str = Field(min_length=1, max_length=500, description="画像描述（中文/英文）")
    importance: float = Field(default=0.7, ge=0.0, le=1.0)


class RelationUpsert(BaseModel):
    subject: str = Field(min_length=1, max_length=256, description="关系主语")
    predicate: str = Field(min_length=1, max_length=64, description="关系类型（动词）")
    object: str = Field(min_length=1, max_length=256, description="关系宾语")
    importance: float = Field(default=0.6, ge=0.0, le=1.0)


@router.get("/personas", response_model=list[LongTermRead])
async def list_personas(
    min_decay: float = Query(default=0.1, ge=0.0, le=1.0),
    limit: int = Query(default=20, ge=1, le=200),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LongTermRead]:
    """v2-M4.2: 列出用户画像（仅 category=persona）。"""
    rows = await long_term.search_personas(db, current.id, min_decay=min_decay, limit=limit)
    return [
        LongTermRead(
            id=r.id, key=r.key, value=r.value, importance=r.importance,
            decay_score=r.decay_score, category=r.category, updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.post("/personas", response_model=LongTermRead, status_code=status.HTTP_201_CREATED)
async def upsert_persona(
    payload: PersonaUpsert,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LongTermRead:
    """v2-M4.2: 创建/更新一条用户画像。"""
    row = await long_term.upsert_persona(
        db, current.id, payload.key, payload.text, importance=payload.importance
    )
    return LongTermRead(
        id=row.id, key=row.key, value=row.value, importance=row.importance,
        decay_score=row.decay_score, category=row.category, updated_at=row.updated_at,
    )


@router.get("/relations", response_model=list[LongTermRead])
async def list_relations(
    subject: str | None = Query(default=None, description="按主语过滤"),
    predicate: str | None = Query(default=None, description="按谓词过滤"),
    object: str | None = Query(default=None, description="按宾语过滤"),
    limit: int = Query(default=50, ge=1, le=200),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LongTermRead]:
    """v2-M4.2: 列出实体关系（仅 category=entity_relation），按 subject/predicate/object 过滤。"""
    rows = await long_term.search_relations(
        db,
        current.id,
        subject=subject,
        predicate=predicate,
        object=object,
        limit=limit,
    )
    return [
        LongTermRead(
            id=r.id, key=r.key, value=r.value, importance=r.importance,
            decay_score=r.decay_score, category=r.category, updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.post("/relations", response_model=LongTermRead, status_code=status.HTTP_201_CREATED)
async def upsert_relation(
    payload: RelationUpsert,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LongTermRead:
    """v2-M4.2: 创建/更新一条实体关系。"""
    row = await long_term.upsert_entity_relation(
        db,
        current.id,
        subject=payload.subject,
        predicate=payload.predicate,
        object=payload.object,
        importance=payload.importance,
    )
    return LongTermRead(
        id=row.id, key=row.key, value=row.value, importance=row.importance,
        decay_score=row.decay_score, category=row.category, updated_at=row.updated_at,
    )


# ---------- v2-M4.1: L3 手动 cluster 触发端点 ----------


class ClusterRunResult(BaseModel):
    events_created: int
    topics_used: int


@router.post("/cluster", response_model=ClusterRunResult)
async def run_cluster(
    days: int = Query(default=7, ge=1, le=30),
    min_topics: int = Query(default=2, ge=2, le=10),
    threshold: float = Query(default=0.85, ge=0.5, le=0.99),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClusterRunResult:
    """v2-M4.1: 手动触发 L2→L3 聚类。事件看板调用。"""
    from app.memory.cluster import run_clustering_for_user

    n_events = await run_clustering_for_user(
        db, current.id, threshold=threshold, min_topics=min_topics, days=days
    )
    # 统计 topic 数（被聚类的）
    from datetime import UTC, datetime, timedelta

    from app.db.models.memory import MemoryMediumTopic

    cutoff = datetime.now(UTC) - timedelta(days=days)
    n_topics = (
        await db.execute(
            select(func.count())
            .select_from(MemoryMediumTopic)
            .where(
                MemoryMediumTopic.user_id == current.id,
                MemoryMediumTopic.created_at >= cutoff,
                MemoryMediumTopic.cluster_id.isnot(None),
            )
        )
    ).scalar() or 0
    return ClusterRunResult(events_created=n_events, topics_used=n_topics)


@router.get("/cluster/last-updated")
async def last_cluster_run(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """v2-P1: 返回上次聚类运行时间（users.last_cluster_run_at，手动/定时更新）。"""
    last = current.last_cluster_run_at
    return {"last_run_at": last.isoformat() if last else None}


# 引入 func（避免上面 select(func.count()) 未导入）
from sqlalchemy import func  # noqa: E402


# ---------- v2-M4.1: 按 email_id 溯源 ----------


class EmailMemoryLink(BaseModel):
    """邮件 → L2 topic + L3 event 关联响应。"""

    email_id: uuid.UUID
    topics: list[TopicRead]
    events: list[EventRead]


@router.get("/emails/{email_id}/memory", response_model=EmailMemoryLink)
async def get_email_memory(
    email_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EmailMemoryLink:
    """v2-M4.1: 列出某邮件产生的 L2 topic + L3 event（通过 source_type/source_id 关联）。

    链路：email → topic (memory_medium_topics.email_id) → cluster_id → event (memory_events.cluster_id)
    """
    # L2 topics
    topics = await medium_term.list_topics_by_email(db, current.id, email_id)
    # L3 events：找 topic 的 cluster_id 对应的 event
    from app.db.models.memory_event import MemoryEvent, MemoryEventTimeline

    cluster_ids = list({t.cluster_id for t in topics if t.cluster_id is not None})
    events_rows: list[MemoryEvent] = []
    if cluster_ids:
        stmt = select(MemoryEvent).where(
            MemoryEvent.user_id == current.id, MemoryEvent.cluster_id.in_(cluster_ids)
        )
        events_rows = list((await db.execute(stmt)).scalars().all())
    # 也通过 timeline.source_id=email_id 兜底（如果邮件的事件流直接 link 到 email）
    if not events_rows:
        tl_stmt = select(MemoryEventTimeline).where(
            MemoryEventTimeline.source_type == "email",
            MemoryEventTimeline.source_id == str(email_id),
        )
        tl_rows = list((await db.execute(tl_stmt)).scalars().all())
        event_ids = list({t.event_id for t in tl_rows})
        if event_ids:
            ev_stmt = select(MemoryEvent).where(
                MemoryEvent.user_id == current.id, MemoryEvent.id.in_(event_ids)
            )
            events_rows = list((await db.execute(ev_stmt)).scalars().all())

    return EmailMemoryLink(
        email_id=email_id,
        topics=[
            TopicRead(id=t.id, topic=t.topic, summary=t.summary, created_at=t.created_at)
            for t in topics
        ],
        events=[
            EventRead(
                id=r.id, title=r.title, summary=r.summary, status=r.status,
                confidence=r.confidence, start_at=r.start_at, end_at=r.end_at,
                created_at=r.created_at, updated_at=r.updated_at,
            )
            for r in events_rows
        ],
    )
