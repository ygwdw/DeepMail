"""邮件相关 DTO。"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.schemas.common import ORMModel


class EmailRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    message_id: str
    thread_id: str | None
    sender_name: str | None
    sender_email: str
    recipients: list[str]
    cc: list[str]
    subject: str
    body_text: str
    sent_at: datetime
    received_at: datetime
    is_read: bool
    spam_score: float
    folder: str
    labels: list[str]
    categories: list[str]
    summary: str | None


class EmailListItem(ORMModel):
    """列表用的精简视图（不含正文）。"""

    id: uuid.UUID
    message_id: str
    thread_id: str | None
    sender_name: str | None
    sender_email: str
    subject: str
    sent_at: datetime
    received_at: datetime
    is_read: bool
    spam_score: float
    folder: str
    labels: list[str]
    categories: list[str]
    summary: str | None
