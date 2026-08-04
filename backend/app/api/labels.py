"""/api/labels 管理。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models.label import Label
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import ORMModel

router = APIRouter(prefix="/api/labels", tags=["labels"])


class LabelRead(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    color: str


class LabelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=2000)
    color: str = Field(default="#888888", max_length=16)


class LabelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    color: str | None = Field(default=None, max_length=16)


@router.get("", response_model=list[LabelRead])
async def list_labels(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LabelRead]:
    stmt = select(Label).where(Label.user_id == current.id).order_by(Label.name)
    rows = (await db.execute(stmt)).scalars().all()
    return [LabelRead.model_validate(lb) for lb in rows]


@router.post("", response_model=LabelRead, status_code=status.HTTP_201_CREATED)
async def create_label(
    payload: LabelCreate,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LabelRead:
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
    return LabelRead.model_validate(label)


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
        label.description = payload.description
    if payload.color is not None:
        label.color = payload.color
    await db.commit()
    await db.refresh(label)
    return LabelRead.model_validate(label)


@router.delete("/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_label(
    label_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    stmt = select(Label).where(Label.id == label_id, Label.user_id == current.id)
    label = (await db.execute(stmt)).scalar_one_or_none()
    if label is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="label not found")
    await db.delete(label)
    await db.commit()
