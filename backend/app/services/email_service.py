"""邮件业务：从 Provider 读取 + 落库 + 提供查询。"""

from __future__ import annotations

import uuid
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.email import Email
from app.services.email_provider.base import EmailPayload, EmailProvider


class EmailService:
    def __init__(self, db: AsyncSession, provider: EmailProvider) -> None:
        self._db = db
        self._provider = provider

    async def list_emails(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Email]:
        stmt = (
            select(Email)
            .where(Email.user_id == user_id)
            .order_by(Email.received_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def get_email(self, user_id: uuid.UUID, email_id: uuid.UUID) -> Email | None:
        stmt = select(Email).where(Email.user_id == user_id, Email.id == email_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def count_emails(self, user_id: uuid.UUID) -> int:
        from sqlalchemy import func

        stmt = select(func.count(Email.id)).where(Email.user_id == user_id)
        return int((await self._db.execute(stmt)).scalar_one())

    async def ensure_from_provider(self, user_id: uuid.UUID) -> int:
        """把 Provider 里的邮件按 user_id 同步进 DB（去重 by message_id）。返回新增条数。"""
        payloads = await self._provider.list_emails(user_id, limit=1000, offset=0)
        existing_stmt = select(Email.message_id).where(Email.user_id == user_id)
        existing = {mid for mid in (await self._db.execute(existing_stmt)).scalars().all()}

        added = 0
        for p in payloads:
            if p.message_id in existing:
                continue
            email = _to_model(user_id, p)
            self._db.add(email)
            added += 1
        if added:
            await self._db.commit()
        return added


def _to_model(user_id: uuid.UUID, p: EmailPayload) -> Email:
    return Email(
        user_id=user_id,
        message_id=p.message_id,
        thread_id=p.thread_id,
        sender_name=p.sender_name,
        sender_email=p.sender_email,
        recipients=p.recipients,
        cc=p.cc,
        subject=p.subject,
        body_text=p.body_text,
        body_html=p.body_html,
        sent_at=p.sent_at if p.sent_at.tzinfo else p.sent_at.replace(tzinfo=UTC),
        received_at=(
            p.received_at if p.received_at.tzinfo else p.received_at.replace(tzinfo=UTC)
        ),
        labels=p.labels,
        categories=p.categories,
        raw_payload=p.raw_payload,
    )
