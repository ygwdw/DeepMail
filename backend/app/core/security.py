"""JWT 签发 / 校验 / 密码哈希。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings

_settings = get_settings()


# ---- 密码 ----


def hash_password(plain: str) -> str:
    # bcrypt 限制 72 字节；本项目密码最长 128 字节（schema 限制），手动截断
    encoded = plain.encode("utf-8")[:72]
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        encoded = plain.encode("utf-8")[:72]
        return bcrypt.checkpw(encoded, hashed.encode("utf-8"))
    except Exception:
        return False


# ---- JWT ----


class TokenError(Exception):
    """Token 解析或校验失败。"""


def _now() -> datetime:
    return datetime.now(UTC)


def create_access_token(
    subject: str | uuid.UUID,
    *,
    extra: dict[str, Any] | None = None,
) -> str:
    expire = _now() + timedelta(minutes=_settings.jwt_access_ttl_minutes)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": "access",
        "iat": int(_now().timestamp()),
        "exp": int(expire.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm)


def create_refresh_token(
    subject: str | uuid.UUID,
    *,
    extra: dict[str, Any] | None = None,
) -> str:
    expire = _now() + timedelta(days=_settings.jwt_refresh_ttl_days)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": "refresh",
        "iat": int(_now().timestamp()),
        "exp": int(expire.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm)


def decode_token(token: str, *, expected_type: str | None = None) -> dict[str, Any]:
    """解码并校验 token。失败抛 TokenError。"""
    try:
        payload = jwt.decode(token, _settings.jwt_secret, algorithms=[_settings.jwt_algorithm])
    except JWTError as exc:
        raise TokenError(f"invalid token: {exc}") from exc

    if expected_type and payload.get("type") != expected_type:
        raise TokenError(f"unexpected token type: {payload.get('type')!r}")
    return payload
