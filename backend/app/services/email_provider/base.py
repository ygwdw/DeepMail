"""邮件 Provider 抽象接口。

Mock / IMAP / SMTP 实现都遵循此接口。
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class EmailPayload(BaseModel):
    """Provider 与上层之间传输的邮件 DTO（避免依赖 ORM）。"""

    message_id: str
    sender_name: str | None = None
    sender_email: str
    recipients: list[str]
    cc: list[str] = []
    subject: str = ""
    body_text: str = ""
    body_html: str | None = None
    sent_at: datetime
    received_at: datetime
    thread_id: str | None = None
    labels: list[str] = []
    categories: list[str] = []
    raw_payload: dict[str, Any] = {}


class EmailProvider(ABC):
    """统一的邮件读写抽象。"""

    name: str = "base"

    @abstractmethod
    async def list_emails(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EmailPayload]:
        """列出邮件（按 received_at 倒序）。"""

    @abstractmethod
    async def get_email(
        self,
        user_id: uuid.UUID,
        message_id: str,
    ) -> EmailPayload | None:
        """按 message_id 取单封（用于入库去重）。"""

    @abstractmethod
    async def send_email(
        self,
        user_id: uuid.UUID,
        *,
        to: list[str],
        subject: str,
        body_text: str,
        body_html: str | None = None,
    ) -> EmailPayload:
        """发送邮件。第一周期 Mock 实现，第二周期切换 SMTP。"""

    @abstractmethod
    async def delete_email(self, user_id: uuid.UUID, message_id: str) -> None: ...

    @abstractmethod
    async def mark_read(self, user_id: uuid.UUID, message_id: str, *, is_read: bool) -> None: ...
