"""Token 用量记录。"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.usage import UsageLog


async def record_usage(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    skill_name: str,
    email_id: uuid.UUID | None,
    tokens_total: int,
    latency_ms: int,
    error: str | None = None,
    tokens_prompt: int = 0,
    tokens_completion: int = 0,
) -> UsageLog:
    """写一条用量日志。"""
    log = UsageLog(
        user_id=user_id,
        skill_name=skill_name,
        email_id=email_id,
        tokens_prompt=tokens_prompt,
        tokens_completion=tokens_completion,
        tokens_total=tokens_total,
        latency_ms=latency_ms,
        error=error,
    )
    db.add(log)
    await db.flush()
    return log
