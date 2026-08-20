"""/api/emails 路由（接 Mock Provider）。"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_email_provider
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.email import EmailListItem, EmailRead, make_body_preview
from app.services.email_provider.base import EmailProvider
from app.services.email_service import EmailService

router = APIRouter(prefix="/api/emails", tags=["emails"])


@router.get("", response_model=Page[EmailListItem])
async def list_emails(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    folder: str = Query(default="all", pattern="^(inbox|sent|spam|trash|all)$"),
    sync: bool = Query(default=False, description="先从 Provider 同步再返回"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    provider: EmailProvider = Depends(get_email_provider),
) -> Page[EmailListItem]:
    from sqlalchemy import func

    svc = EmailService(db, provider)
    if sync:
        await svc.ensure_from_provider(current.id)

    from sqlalchemy import select as _select

    from app.db.models.email import Email as _Email

    base_where = [_Email.user_id == current.id]
    if folder != "all":
        base_where.append(_Email.folder == folder)

    stmt = (
        _select(_Email)
        .where(*base_where)
        .order_by(_Email.received_at.desc())
        .limit(limit)
        .offset(offset)
    )
    count_stmt = _select(func.count(_Email.id)).where(*base_where)

    rows = list((await db.execute(stmt)).scalars().all())
    total = int((await db.execute(count_stmt)).scalar_one())
    return Page[EmailListItem](
        items=[
            EmailListItem(
                id=r.id,
                message_id=r.message_id,
                thread_id=r.thread_id,
                sender_name=r.sender_name,
                sender_email=r.sender_email,
                subject=r.subject,
                sent_at=r.sent_at,
                received_at=r.received_at,
                is_read=r.is_read,
                spam_score=r.spam_score,
                folder=r.folder,
                labels=r.labels,
                categories=r.categories,
                summary=r.summary,
                todos_extracted=r.todos_extracted or [],
                body_preview=make_body_preview(r.body_text),
            )
            for r in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{email_id}", response_model=EmailRead)
async def get_email(
    email_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    provider: EmailProvider = Depends(get_email_provider),
) -> EmailRead:
    svc = EmailService(db, provider)
    row = await svc.get_email(current.id, email_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="email not found")
    return EmailRead.model_validate(row)


class ReclassifyRequest(BaseModel):
    email_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    do_tag: bool = True


class SendEmailRequest(BaseModel):
    to: list[str] = Field(min_length=1, max_length=20)
    cc: list[str] = Field(default_factory=list, max_length=20)
    subject: str = Field(min_length=1, max_length=500)
    body_text: str = Field(min_length=1)
    body_html: str | None = None


@router.post("/send", status_code=status.HTTP_201_CREATED)
async def send_email(
    payload: SendEmailRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    provider: EmailProvider = Depends(get_email_provider),
) -> dict:
    """v2-M12: 发送邮件（真实 SMTP）+ 存 sent folder。"""
    svc = EmailService(db, provider)
    try:
        email = await svc.send_email(
            current.id,
            to=payload.to,
            subject=payload.subject,
            body_text=payload.body_text,
            body_html=payload.body_html,
            cc=payload.cc,
        )
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail="当前 Provider 不支持 SMTP 发送（需要 email_provider=imap + smtp 配置）",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"发送失败: {type(exc).__name__}: {exc}")
    return {"sent": True, "email_id": str(email.id), "folder": "sent", "to": payload.to}


@router.post("/reclassify", status_code=status.HTTP_200_OK)
async def reclassify(
    payload: ReclassifyRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """v2-M12: 批量重新分类/打标。

    对选中邮件重新跑 classify（单分类，覆盖）+ tag_recommend（多标签，覆盖）。
    逐封串行（每封 2 次 LLM 调用）；失败邮件单独返回。
    """
    from app.llm.factory import get_chat_model
    from app.services.ai_service import reclassify_emails

    llm = await get_chat_model(db, current.id)
    return await reclassify_emails(
        llm,
        db,
        current.id,
        payload.email_ids,
        do_tag=payload.do_tag,
    )


@router.post("/sync", status_code=status.HTTP_200_OK)
async def sync_from_provider(
    source: str = Query(default="mock", description="mock | imap"),
    force: bool = Query(
        default=False,
        description="v2-M3: IMAP 模式下 force=true 才允许重跑（默认已同步则拒绝）",
    ),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    provider: EmailProvider = Depends(get_email_provider),
) -> dict[str, Any]:
    """同步邮件到 DB。

    v2-M3:
    - source=mock：原行为（拉 mock 邮件）
    - source=imap：调 IMAP 一次性同步最近 N 封（默认 30）
    """
    svc = EmailService(db, provider)
    if source == "imap":
        result = await svc.onetime_sync_imap(current.id, force=force)
        result["total"] = await svc.count_emails(current.id)
        return result
    # 默认 mock
    added = await svc.ensure_from_provider(current.id)
    total = await svc.count_emails(current.id)
    return {"added": added, "total": total, "source": "mock"}
