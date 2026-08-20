"""/api/dashboard/* 路由。"""

from __future__ import annotations

from datetime import date as _date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.services import dashboard_service
from app.services import digest_service

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/events")
async def get_dashboard(
    days: int = Query(default=30, ge=1, le=365),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回重点事件看板：按周 + 按状态 + 时间线 + 话题。"""
    return await dashboard_service.build_dashboard(db, current.id, days=days)


@router.post("/digest")
async def get_digest(
    payload: dict | None = None,
    date_str: str | None = Query(default=None, alias="date", description="YYYY-MM-DD"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """v2-M9: 获取指定日期的邮件日报。命中缓存直接返回；否则调 LLM 生成。"""
    target_date = date_str
    if payload and isinstance(payload, dict):
        target_date = payload.get("date") or target_date
    if not target_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="date is required (YYYY-MM-DD)")

    try:
        d = _date.fromisoformat(target_date)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid date format (YYYY-MM-DD)")

    return await digest_service.get_or_generate_daily_digest(db, current.id, d)


@router.post("/weekly")
async def get_weekly(
    payload: dict | None = None,
    week_start: str | None = Query(default=None, description="YYYY-MM-DD（周一）"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """v2-M9: 获取指定周（从周一开始）的邮件周报。命中缓存直接返回；否则调 LLM 生成。"""
    target_week = week_start
    if payload and isinstance(payload, dict):
        target_week = payload.get("week_start") or target_week
    if not target_week:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="week_start is required (YYYY-MM-DD)")

    try:
        d = _date.fromisoformat(target_week)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid date format (YYYY-MM-DD)")

    return await digest_service.get_or_generate_weekly_digest(db, current.id, d)