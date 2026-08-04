"""认证业务逻辑。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.db.models.user import User, UserRole
from app.services.category_seed import seed_default_categories


class AuthError(Exception):
    """认证失败。"""


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    stmt = select(User).where(User.username == username)
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    role: UserRole = UserRole.USER,
) -> User:
    if await get_user_by_username(db, username):
        raise AuthError(f"username '{username}' already exists")
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    # 自动 seed 默认分类
    await seed_default_categories(db, user.id)
    return user


async def authenticate(db: AsyncSession, *, username: str, password: str) -> User:
    user = await get_user_by_username(db, username)
    if user is None or not user.is_active:
        raise AuthError("invalid credentials")
    if not verify_password(password, user.password_hash):
        raise AuthError("invalid credentials")
    return user


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)
