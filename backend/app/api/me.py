"""/api/me 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.auth import UserPublic

router = APIRouter(prefix="/api/me", tags=["me"])


class MeRead(UserPublic):
    """当前用户信息（含 token_budget）。"""

    token_budget: int = Field(default=8000, ge=2000, le=32000)


class MeUpdate(BaseModel):
    token_budget: int | None = Field(default=None, ge=2000, le=32000)


@router.get("", response_model=MeRead)
async def me(
    current: User = Depends(get_current_user),
) -> MeRead:
    return MeRead(
        id=current.id,
        username=current.username,
        role=current.role.value,
        is_active=current.is_active,
        token_budget=current.token_budget,
    )


@router.patch("", response_model=MeRead)
async def update_me(
    payload: MeUpdate,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeRead:
    if payload.token_budget is not None:
        current.token_budget = payload.token_budget
        await db.commit()
        await db.refresh(current)
    return MeRead(
        id=current.id,
        username=current.username,
        role=current.role.value,
        is_active=current.is_active,
        token_budget=current.token_budget,
    )
