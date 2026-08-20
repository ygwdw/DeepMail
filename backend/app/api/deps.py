"""FastAPI 依赖注入。"""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenError, decode_token
from app.db.models.user import User, UserRole
from app.db.session import get_db
from app.services.auth_service import get_user_by_id

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(token, expected_type="access")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    user_id = uuid.UUID(payload["sub"])
    user = await get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    return user


def get_email_provider() -> EmailProvider:  # type: ignore[name-defined]
    """根据配置返回 EmailProvider（mock / imap）。

    v2-M3: settings.email_provider == "imap" 时返回 IMAPEmailProvider。
    IMAP 凭据缺失则兜底 mock（保证接口可用）。
    """
    from app.core.config import get_settings
    from app.services.email_provider.mock_provider import MockEmailProvider

    settings = get_settings()
    if settings.email_provider == "imap":
        try:
            from app.services.email_provider.imap_provider import IMAPEmailProvider

            return IMAPEmailProvider()
        except Exception:
            # IMAP 凭据缺失或初始化失败 → 兜底 mock
            import logging

            logging.getLogger(__name__).warning(
                "imap_provider_init_fallback_to_mock",
            )
    return MockEmailProvider()
