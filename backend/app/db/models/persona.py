"""用户人格画像。"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Persona(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "personas"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    # 结构: { profession, personality, communication_style, frequent_topics, signatures }
    profile_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
