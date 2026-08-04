"""邮件模型。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Email(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "emails"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # IMAP/SMTP 标识
    message_id: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    # 发件 / 收件
    sender_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sender_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    recipients: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    cc: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    # 内容
    subject: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    body_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 时间
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # 用户标注 / AI 结果
    is_read: Mapped[bool] = mapped_column(default=False, nullable=False)
    spam_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    folder: Mapped[str] = mapped_column(String(16), default="inbox", nullable=False, index=True)
    labels: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    categories: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    # AI 处理结果（阶段 1 写入）
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    todos_extracted: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    entities_extracted: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
