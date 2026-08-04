"""/api/emails/{id}/* AI 相关路由。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models.email import Email
from app.db.models.label import Label
from app.db.models.user import User
from app.db.session import get_db
from app.llm import get_chat_model
from app.services import ai_service
from app.services.email_service import EmailService

router = APIRouter(prefix="/api/emails", tags=["ai"])


async def _load_email(db: AsyncSession, user_id: uuid.UUID, email_id: uuid.UUID) -> Email:
    email = await EmailService(db, provider=None).get_email(user_id, email_id)  # type: ignore[arg-type]
    if email is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="email not found")
    return email


def _to_result_dict(result) -> dict:
    from app.services.ai_service import _serialize_output

    return {
        "skill": getattr(result, "skill_name", ""),
        "output": _serialize_output(result.output) if result.ok else None,
        "tokens_used": result.tokens_total,
        "latency_ms": result.latency_ms,
        "error": result.error,
    }


# ---------- 1. process（跑全 5 项） ----------


@router.post("/{email_id}/process")
async def process_email(
    email_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    email = await _load_email(db, current.id, email_id)
    llm = await get_chat_model(db, current.id)
    return await ai_service.run_process(llm, db, email, current.id)


# ---------- 2. summary ----------


@router.post("/{email_id}/summary")
async def run_summary(
    email_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    email = await _load_email(db, current.id, email_id)
    llm = await get_chat_model(db, current.id)
    result = await ai_service.run_summary(llm, db, email, current.id)
    await db.commit()
    return _to_result_dict(result)


# ---------- 3. todos ----------


@router.post("/{email_id}/todos")
async def run_todos(
    email_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    email = await _load_email(db, current.id, email_id)
    llm = await get_chat_model(db, current.id)
    result = await ai_service.run_todo_extract(llm, db, email, current.id)
    await db.commit()
    return _to_result_dict(result)


# ---------- 4. entities ----------


@router.post("/{email_id}/entities")
async def run_entities(
    email_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    email = await _load_email(db, current.id, email_id)
    llm = await get_chat_model(db, current.id)
    result = await ai_service.run_entity_extract(llm, db, email, current.id)
    await db.commit()
    return _to_result_dict(result)


# ---------- 5. classify ----------


@router.post("/{email_id}/classify")
async def run_classify(
    email_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    email = await _load_email(db, current.id, email_id)
    llm = await get_chat_model(db, current.id)
    result = await ai_service.run_classify(llm, db, email, current.id)
    await db.commit()
    return _to_result_dict(result)


# ---------- 6. spam ----------


@router.post("/{email_id}/spam")
async def run_spam(
    email_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    email = await _load_email(db, current.id, email_id)
    llm = await get_chat_model(db, current.id)
    result = await ai_service.run_spam(llm, db, email, current.id)
    await db.commit()
    return _to_result_dict(result)


# ---------- 7. tag recommend（不入库） ----------


@router.post("/{email_id}/tag/recommend")
async def run_tag_recommend(
    email_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    email = await _load_email(db, current.id, email_id)
    llm = await get_chat_model(db, current.id)
    result = await ai_service.run_tag_recommend(llm, db, email, current.id)
    await db.commit()
    return _to_result_dict(result)


# ---------- 8. labels（用户确认落库） ----------


class LabelsConfirmRequest(BaseModel):
    labels: list[str]


@router.post("/{email_id}/labels")
async def confirm_labels(
    email_id: uuid.UUID,
    payload: LabelsConfirmRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    email = await _load_email(db, current.id, email_id)
    # 自动创建不存在的 label
    from sqlalchemy import select

    stmt = select(Label).where(Label.user_id == current.id)
    existing = {lb.name for lb in (await db.execute(stmt)).scalars().all()}
    for name in payload.labels:
        if name not in existing:
            db.add(Label(user_id=current.id, name=name, color="#888888"))
            existing.add(name)
    email.labels = list(dict.fromkeys(payload.labels))  # 去重保序
    await db.commit()
    return {"email_id": str(email.id), "labels": email.labels}


# ---------- 9. draft ----------


class DraftRequest(BaseModel):
    instruction: str
    tone: str = "auto"  # formal / casual / auto


@router.post("/{email_id}/draft")
async def run_draft(
    email_id: uuid.UUID,
    payload: DraftRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    email = await _load_email(db, current.id, email_id)
    llm = await get_chat_model(db, current.id)
    result = await ai_service.run_draft(
        llm, db, email, current.id, instruction=payload.instruction, tone=payload.tone
    )
    await db.commit()
    return _to_result_dict(result)
