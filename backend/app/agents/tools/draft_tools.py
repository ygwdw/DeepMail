"""草稿工具。"""

from __future__ import annotations

import json
import uuid

from langchain_core.tools import tool
from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models.email import Email
from app.llm.factory import get_chat_model
from app.services import ai_service

_logger = get_logger(__name__)


@tool
async def draft_reply(
    email_id: str,
    instruction: str,
    tone: str = "auto",
) -> str:
    """为一封邮件起草回复（基于联系人历史）。

    Args:
        email_id: 原邮件 UUID
        instruction: 起草要求（中文/英文，按用户原话）
        tone: formal / casual / auto

    Returns:
        草稿文本
    """
    from app.agents.tools.context import get_current_user_id

    user_id = get_current_user_id()
    if user_id is None:
        return "no user context"
    _logger.info("tool_call", tool="draft_reply", email_id=email_id, tone=tone)
    from app.db.session import get_sessionmaker

    sm = get_sessionmaker()
    async with sm() as db:
        em = (
            await db.execute(
                select(Email).where(
                    Email.user_id == uuid.UUID(user_id), Email.id == uuid.UUID(email_id)
                )
            )
        ).scalar_one_or_none()
        if em is None:
            return "email not found"
        llm = await get_chat_model(db, uuid.UUID(user_id))
        result = await ai_service.run_draft(
            llm, db, em, uuid.UUID(user_id), instruction=instruction, tone=tone
        )
        await db.commit()
        if not result.ok:
            return f"error: {result.error}"
        return json.dumps(
            {
                "draft_text": result.output.draft_text,
                "key_points": result.output.key_points,
            },
            ensure_ascii=False,
        )
