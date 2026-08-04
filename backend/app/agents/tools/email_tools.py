"""Email 相关 LangChain 工具。"""

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


async def _get_session():
    """返回 async_sessionmaker（不是 session），调用方：async with sm() as db。"""
    from app.db.session import get_sessionmaker

    return get_sessionmaker()


@tool
async def list_emails(folder: str = "inbox", limit: int = 10) -> str:
    """列出邮件。

    Args:
        folder: inbox / sent / spam / trash / all
        limit: 返回数量（1-50）

    Returns:
        JSON 字符串，邮件列表（不含正文）
    """
    _logger.info("tool_call", tool="list_emails", folder=folder, limit=limit)
    from app.agents.tools.context import get_current_user_id

    user_id = get_current_user_id()
    if user_id is None:
        return json.dumps({"error": "no user context"})
    sm = await _get_session()
    async with sm() as db:
        from sqlalchemy import func

        stmt = select(Email).where(Email.user_id == uuid.UUID(user_id))
        if folder != "all":
            stmt = stmt.where(Email.folder == folder)
        count_stmt = select(func.count(Email.id)).where(Email.user_id == uuid.UUID(user_id))
        if folder != "all":
            count_stmt = count_stmt.where(Email.folder == folder)
        stmt = stmt.order_by(Email.received_at.desc()).limit(limit)
        rows = list((await db.execute(stmt)).scalars().all())
        total = int((await db.execute(count_stmt)).scalar_one())
    items = [
        {
            "id": str(r.id),
            "subject": r.subject,
            "sender": r.sender_email,
            "received_at": r.received_at.isoformat() if r.received_at else None,
            "is_read": r.is_read,
            "categories": r.categories,
            "summary": r.summary,
        }
        for r in rows
    ]
    return json.dumps({"total": total, "items": items}, ensure_ascii=False)


@tool
async def get_email(email_id: str) -> str:
    """获取单封邮件详情（含正文）。

    Args:
        email_id: 邮件 UUID

    Returns:
        JSON 字符串
    """
    from app.agents.tools.context import get_current_user_id

    _logger.info("tool_call", tool="get_email", email_id=email_id)
    user_id = get_current_user_id()
    if user_id is None:
        return json.dumps({"error": "no user context"})
    sm = await _get_session()
    async with sm() as db:
        em = (
            await db.execute(
                select(Email).where(
                    Email.user_id == uuid.UUID(user_id), Email.id == uuid.UUID(email_id)
                )
            )
        ).scalar_one_or_none()
        if em is None:
            return json.dumps({"error": "email not found"})
        return json.dumps(
            {
                "id": str(em.id),
                "subject": em.subject,
                "sender": em.sender_email,
                "body_text": em.body_text,
                "categories": em.categories,
                "labels": em.labels,
                "received_at": em.received_at.isoformat(),
                "summary": em.summary,
                "is_read": em.is_read,
            },
            ensure_ascii=False,
        )


@tool
async def summarize_email(email_id: str) -> str:
    """对单封邮件生成摘要。

    Args:
        email_id: 邮件 UUID

    Returns:
        摘要文本
    """
    from app.agents.tools.context import get_current_user_id

    _logger.info("tool_call", tool="summarize_email", email_id=email_id)
    user_id = get_current_user_id()
    if user_id is None:
        return "no user context"
    sm = await _get_session()
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
        result = await ai_service.run_summary(llm, db, em, uuid.UUID(user_id))
        await db.commit()
        if not result.ok:
            return f"error: {result.error}"
        return json.dumps(
            {"summary": result.output.summary, "key_points": result.output.key_points},
            ensure_ascii=False,
        )


@tool
async def classify_email(email_id: str) -> str:
    """对单封邮件跑分类（写入 DB 并返回）。"""
    from app.agents.tools.context import get_current_user_id

    _logger.info("tool_call", tool="classify_email", email_id=email_id)
    user_id = get_current_user_id()
    if user_id is None:
        return "no user context"
    sm = await _get_session()
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
        result = await ai_service.run_classify(llm, db, em, uuid.UUID(user_id))
        await db.commit()
        if not result.ok:
            return f"error: {result.error}"
        return json.dumps(
            {"category": result.output.category_name, "confidence": result.output.confidence},
            ensure_ascii=False,
        )
