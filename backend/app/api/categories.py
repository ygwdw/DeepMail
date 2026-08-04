"""/api/categories 管理。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models.label import Category
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import ORMModel

router = APIRouter(prefix="/api/categories", tags=["categories"])


class CategoryRead(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    rules_json: dict
    is_system: bool
    is_spam_category: bool


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=2000)
    rules_json: dict = Field(default_factory=dict)
    is_spam_category: bool = False


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    rules_json: dict | None = None
    is_spam_category: bool | None = None


@router.get("", response_model=list[CategoryRead])
async def list_categories(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CategoryRead]:
    stmt = (
        select(Category)
        .where(Category.user_id == current.id)
        .order_by(Category.is_system.desc(), Category.name)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [CategoryRead.model_validate(c) for c in rows]


@router.post("", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CategoryRead:
    cat = Category(
        user_id=current.id,
        name=payload.name,
        description=payload.description,
        rules_json=payload.rules_json,
        is_system=False,
        is_spam_category=payload.is_spam_category,
    )
    db.add(cat)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"category exists: {exc}")
    await db.refresh(cat)
    return CategoryRead.model_validate(cat)


@router.patch("/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: uuid.UUID,
    payload: CategoryUpdate,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CategoryRead:
    stmt = select(Category).where(Category.id == category_id, Category.user_id == current.id)
    cat = (await db.execute(stmt)).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="category not found")
    if cat.is_system and payload.name is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="系统预设分类不可改名")
    if payload.name is not None:
        cat.name = payload.name
    if payload.description is not None:
        cat.description = payload.description
    if payload.rules_json is not None:
        cat.rules_json = payload.rules_json
    if payload.is_spam_category is not None:
        cat.is_spam_category = payload.is_spam_category
    await db.commit()
    await db.refresh(cat)
    return CategoryRead.model_validate(cat)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    stmt = select(Category).where(Category.id == category_id, Category.user_id == current.id)
    cat = (await db.execute(stmt)).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="category not found")
    if cat.is_system:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="系统预设分类不可删除")
    await db.delete(cat)
    await db.commit()
