"""待办事项。"""

from __future__ import annotations

import enum
import uuid
from datetime import date

from sqlalchemy import Date, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class TodoStatus(enum.StrEnum):
    PENDING = "pending"
    DONE = "done"
    CANCELLED = "cancelled"


class TodoPriority(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Todo(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "todos"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("emails.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[TodoStatus] = mapped_column(
        Enum(
            TodoStatus,
            name="todo_status",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        default=TodoStatus.PENDING,
        nullable=False,
    )
    priority: Mapped[TodoPriority] = mapped_column(
        Enum(
            TodoPriority,
            name="todo_priority",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        default=TodoPriority.MEDIUM,
        nullable=False,
    )
