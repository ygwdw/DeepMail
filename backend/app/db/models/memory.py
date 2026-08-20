"""中期话题记忆 / 长期语义记忆。"""

from __future__ import annotations

import uuid
from datetime import UTC

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.db.base import Base
from app.db.models.mixins import UUIDPrimaryKeyMixin

_settings = get_settings()
_EMBED_DIM = _settings.llm_embed_dim


def _utcnow():
    from datetime import datetime

    return datetime.now(UTC)


class MemoryMediumTopic(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "memory_medium_topics"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    embedding = mapped_column(Vector(_EMBED_DIM), nullable=True)
    # v2-M4.1: 来源追溯（哪封邮件/哪个会话产生的 topic）
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    chat_session_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    # 聚类到 L3 后回填 cluster_id
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    created_at: Mapped[DateTime] = mapped_column(  # type: ignore[valid-type]
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class MemoryLongTerm(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "memory_long_term"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    importance: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    decay_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="misc", nullable=False, index=True)
    updated_at: Mapped[DateTime] = mapped_column(  # type: ignore[valid-type]
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )
