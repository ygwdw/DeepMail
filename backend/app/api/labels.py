"""/api/labels 管理（v2-M6 增强：返回 count）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models.email import Email
from app.db.models.label import Label
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import ORMModel

router = APIRouter(prefix="/api/labels", tags=["labels"])

USER_LABEL_DESC_MIN = 5  # 标签描述比分类宽松（标签是关键词性质）


class LabelRead(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    color: str
    count: int = 0  # v2-M6：标签下邮件数


class LabelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=2000)
    color: str = Field(default="#1890ff", max_length=16)


class LabelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    color: str | None = Field(default=None, max_length=16)


def _validate_color(color: str) -> None:
    if not color.startswith("#") or len(color) not in (4, 7, 9):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="color 必须是 #RGB / #RRGGBB / #RRGGBBAA 格式",
        )


async def _list_with_counts(
    db: AsyncSession, user_id: uuid.UUID
) -> list[tuple[Label, int]]:
    stmt = select(Label).where(Label.user_id == user_id).order_by(Label.name)
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        return []
    label_names = [lb.name for lb in rows]
    # 一次拉所有 emails.labels
    label_rows = (
        await db.execute(
            select(Email.labels).where(Email.user_id == user_id)
        )
    ).scalars().all()
    counts: dict[str, int] = {n: 0 for n in label_names}
    for labels in label_rows:
        if not labels:
            continue
        for n in label_names:
            if n in labels:
                counts[n] += 1
    return [(lb, counts[lb.name]) for lb in rows]


@router.get("", response_model=list[LabelRead])
async def list_labels(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LabelRead]:
    rows = await _list_with_counts(db, current.id)
    return [
        LabelRead(
            id=lb.id,
            name=lb.name,
            description=lb.description,
            color=lb.color,
            count=count,
        )
        for lb, count in rows
    ]


@router.post("", response_model=LabelRead, status_code=status.HTTP_201_CREATED)
async def create_label(
    payload: LabelCreate,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LabelRead:
    if len(payload.description.strip()) < USER_LABEL_DESC_MIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"description 必须 ≥ {USER_LABEL_DESC_MIN} 字（帮助 LLM 打标）",
        )
    _validate_color(payload.color)
    label = Label(
        user_id=current.id,
        name=payload.name,
        description=payload.description,
        color=payload.color,
    )
    db.add(label)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"label exists: {exc}")
    await db.refresh(label)
    return LabelRead(
        id=label.id,
        name=label.name,
        description=label.description,
        color=label.color,
        count=0,
    )


@router.patch("/{label_id}", response_model=LabelRead)
async def update_label(
    label_id: uuid.UUID,
    payload: LabelUpdate,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LabelRead:
    stmt = select(Label).where(Label.id == label_id, Label.user_id == current.id)
    label = (await db.execute(stmt)).scalar_one_or_none()
    if label is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="label not found")
    if payload.name is not None:
        label.name = payload.name
    if payload.description is not None:
        if len(payload.description.strip()) < USER_LABEL_DESC_MIN:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"description 必须 ≥ {USER_LABEL_DESC_MIN} 字",
            )
        label.description = payload.description
    if payload.color is not None:
        _validate_color(payload.color)
        label.color = payload.color
    await db.commit()
    await db.refresh(label)
    rows = await _list_with_counts(db, current.id)
    counts = {lb.id: cnt for lb, cnt in rows}
    return LabelRead(
        id=label.id,
        name=label.name,
        description=label.description,
        color=label.color,
        count=counts.get(label.id, 0),
    )


@router.delete("/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_label(
    label_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """删除标签；非空标签：把所有邮件的 labels 数组中该标签名移除。"""
    stmt = select(Label).where(Label.id == label_id, Label.user_id == current.id)
    label = (await db.execute(stmt)).scalar_one_or_none()
    if label is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="label not found")
    # 从所有邮件的 labels 数组中移除该标签
    email_stmt = select(Email).where(
        Email.user_id == current.id,
        Email.labels.contains_([label.name]),
    )
    emails = list((await db.execute(email_stmt)).scalars().all())
    for em in emails:
        em.labels = [x for x in (em.labels or []) if x != label.name]
    await db.delete(label)
    await db.commit()