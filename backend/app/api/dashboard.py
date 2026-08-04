"""/api/dashboard/* 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.services import dashboard_service

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/events")
async def get_dashboard(
    days: int = Query(default=30, ge=1, le=365),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回重点事件看板：按周 + 按状态 + 时间线 + 话题。"""
    return await dashboard_service.build_dashboard(db, current.id, days=days)
