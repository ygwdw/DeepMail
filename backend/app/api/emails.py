"""/api/emails 路由（接 Mock Provider）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_email_provider
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.email import EmailListItem, EmailRead
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
        items=[EmailListItem.model_validate(r) for r in rows],
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


@router.post("/sync", status_code=status.HTTP_200_OK)
async def sync_from_provider(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    provider: EmailProvider = Depends(get_email_provider),
) -> dict[str, int]:
    svc = EmailService(db, provider)
    added = await svc.ensure_from_provider(current.id)
    total = await svc.count_emails(current.id)
    return {"added": added, "total": total}
