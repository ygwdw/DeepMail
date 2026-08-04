"""/api/auth/* 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserPublic,
)
from app.services.auth_service import AuthError, authenticate, create_user

router = APIRouter(prefix="/api/auth", tags=["auth"])
_settings = get_settings()


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)) -> User:
    try:
        user = await create_user(db, username=payload.username, password=payload.password)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return user


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenPair:
    try:
        user = await authenticate(db, username=payload.username, password=payload.password)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    extra = {"role": user.role.value, "username": user.username}
    access = create_access_token(user.id, extra=extra)
    refresh = create_refresh_token(user.id, extra=extra)
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=_settings.jwt_access_ttl_minutes * 60,
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenPair:
    try:
        decoded = decode_token(payload.refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    from uuid import UUID

    from app.services.auth_service import get_user_by_id

    user = await get_user_by_id(db, UUID(decoded["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")

    extra = {"role": user.role.value, "username": user.username}
    access = create_access_token(user.id, extra=extra)
    new_refresh = create_refresh_token(user.id, extra=extra)
    return TokenPair(
        access_token=access,
        refresh_token=new_refresh,
        expires_in=_settings.jwt_access_ttl_minutes * 60,
    )


@router.get("/me", response_model=UserPublic)
async def me(current: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic(
        id=current.id,
        username=current.username,
        role=current.role.value,
        is_active=current.is_active,
    )
