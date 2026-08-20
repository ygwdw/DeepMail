"""/api/categories 管理（v2-M6 增强）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models.email import Email
from app.db.models.label import Category
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import ORMModel

router = APIRouter(prefix="/api/categories", tags=["categories"])

# 用户自定义分类的 description 最小长度（帮助 LLM 分类）
USER_CATEGORY_DESC_MIN = 10
DEFAULT_CATEGORY_NAME = "常规"


class CategoryRead(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    rules_json: dict
    is_system: bool
    is_spam_category: bool
    count: int = 0  # 该分类下的邮件数（v2-M6）


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


class CategoryDeleteResponse(BaseModel):
    moved_to: str
    moved_count: int


def _validate_user_description(name: str, description: str, is_system: bool) -> None:
    """用户自定义分类时 description 必须 ≥ 10 字。系统分类由 seed 写入，跳过。"""
    if is_system:
        return
    if not description or len(description.strip()) < USER_CATEGORY_DESC_MIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"用户自定义分类 description 必须 ≥ {USER_CATEGORY_DESC_MIN} 字（帮助 LLM 分类）",
        )


async def _list_with_counts(
    db: AsyncSession, user_id: uuid.UUID
) -> list[tuple[Category, int]]:
    """返回 (Category, count) 列表，按 系统分类优先 + 名字排序。"""
    count_subq = (
        select(Email.id, Email.categories)
        .where(Email.user_id == user_id)
        .subquery()
    )
    # 用 Python 端聚合（分类数 < 20，N+1 可接受）
    stmt = (
        select(Category)
        .where(Category.user_id == user_id)
        .order_by(Category.is_system.desc(), Category.name)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    cat_names = [c.name for c in rows]
    if not cat_names:
        return []
    # 一次拉所有 categories，再 Python 聚合
    cat_rows = (
        await db.execute(
            select(Email.categories).where(Email.user_id == user_id)
        )
    ).scalars().all()
    counts: dict[str, int] = {n: 0 for n in cat_names}
    for cats in cat_rows:
        if not cats:
            continue
        for n in cat_names:
            if n in cats:
                counts[n] += 1
    return [(c, counts[c.name]) for c in rows]


@router.get("", response_model=list[CategoryRead])
async def list_categories(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CategoryRead]:
    rows = await _list_with_counts(db, current.id)
    return [
        CategoryRead(
            id=c.id,
            name=c.name,
            description=c.description,
            rules_json=c.rules_json,
            is_system=c.is_system,
            is_spam_category=c.is_spam_category,
            count=count,
        )
        for c, count in rows
    ]


@router.post("", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CategoryRead:
    _validate_user_description(payload.name, payload.description, is_system=False)
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
    return CategoryRead(
        id=cat.id,
        name=cat.name,
        description=cat.description,
        rules_json=cat.rules_json,
        is_system=cat.is_system,
        is_spam_category=cat.is_spam_category,
        count=0,
    )


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
        # 描述可以任意修改（系统分类的描述也可改，不算"改"）
        if not cat.is_system and len(payload.description.strip()) < USER_CATEGORY_DESC_MIN:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"用户自定义分类 description 必须 ≥ {USER_CATEGORY_DESC_MIN} 字",
            )
        cat.description = payload.description
    if payload.rules_json is not None:
        cat.rules_json = payload.rules_json
    if payload.is_spam_category is not None:
        cat.is_spam_category = payload.is_spam_category
    await db.commit()
    await db.refresh(cat)
    # 重新计算 count
    rows = await _list_with_counts(db, current.id)
    counts = {c.id: cnt for c, cnt in rows}
    return CategoryRead(
        id=cat.id,
        name=cat.name,
        description=cat.description,
        rules_json=cat.rules_json,
        is_system=cat.is_system,
        is_spam_category=cat.is_spam_category,
        count=counts.get(cat.id, 0),
    )


@router.delete("/{category_id}", response_model=CategoryDeleteResponse)
async def delete_category(
    category_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CategoryDeleteResponse:
    """删除用户自定义分类；如果是默认分类则不可删。

    非空分类：把所有邮件的 categories 数组中该分类名替换为默认分类（"常规"）。
    """
    stmt = select(Category).where(Category.id == category_id, Category.user_id == current.id)
    cat = (await db.execute(stmt)).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="category not found")
    if cat.is_system:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="系统预设分类不可删除")
    if cat.name == DEFAULT_CATEGORY_NAME:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="默认分类不可删除")

    # 找默认分类作为迁移目标
    default_stmt = select(Category).where(
        Category.user_id == current.id,
        Category.name == DEFAULT_CATEGORY_NAME,
    )
    default_cat = (await db.execute(default_stmt)).scalar_one_or_none()
    if default_cat is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="default category missing; run init_db.py to seed",
        )

    # 找到所有含 cat.name 的邮件，把 cat.name 替换为 default_cat.name
    email_stmt = select(Email).where(
        Email.user_id == current.id,
        Email.categories.contains_([cat.name]),
    )
    emails = list((await db.execute(email_stmt)).scalars().all())
    moved = 0
    for em in emails:
        new_cats = []
        for x in em.categories or []:
            if x == cat.name:
                new_cats.append(default_cat.name)
            else:
                new_cats.append(x)
        if DEFAULT_CATEGORY_NAME not in new_cats:
            new_cats.append(default_cat.name)
        em.categories = new_cats
        moved += 1

    # 真正删分类
    await db.delete(cat)
    await db.commit()
    return CategoryDeleteResponse(moved_to=default_cat.name, moved_count=moved)