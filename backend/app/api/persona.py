"""/api/persona/* 路由。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import ORMModel
from app.services import persona_service

router = APIRouter(prefix="/api/persona", tags=["persona"])


# ---------- Schemas ----------


class PersonaRead(ORMModel):
    profile_json: dict
    updated_at: datetime


class PersonaUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    age: int | None = Field(default=None, ge=0, le=120)
    education: str | None = Field(default=None, max_length=128)
    profession: str | None = Field(default=None, max_length=64)
    personality: list[str] | None = None
    communication_style: str | None = Field(default=None, max_length=64)
    language_pref: str | None = Field(default=None, max_length=64)
    signature: str | None = Field(default=None, max_length=255)
    frequent_topics: list[str] | None = None
    sample_phrases: list[str] | None = None


# ---------- 路由 ----------


@router.get("", response_model=PersonaRead)
async def get_persona(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersonaRead:
    persona = await persona_service.get_or_create_persona(db, current.id)
    return PersonaRead(
        profile_json=persona.profile_json or {},
        updated_at=persona.updated_at,
    )


@router.patch("", response_model=PersonaRead)
async def update_persona(
    payload: PersonaUpdate,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersonaRead:
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    persona = await persona_service.update_persona_fields(
        db, current.id, fields, reason="manual PATCH"
    )
    return PersonaRead(
        profile_json=persona.profile_json or {},
        updated_at=persona.updated_at,
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_persona(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """清空 persona（回滚到空）。"""
    await persona_service.rollback_persona(db, current.id)


@router.post("/rollback", response_model=PersonaRead)
async def rollback_persona_endpoint(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersonaRead:
    """回滚 persona 到空（v1 不存历史，=DELETE）。"""
    persona = await persona_service.rollback_persona(db, current.id)
    if persona is None:
        raise HTTPException(status_code=404, detail="persona not found")
    return PersonaRead(
        profile_json=persona.profile_json or {},
        updated_at=persona.updated_at,
    )
