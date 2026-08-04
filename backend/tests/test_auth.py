"""鉴权相关单测：密码 hash、JWT 编解码。"""

from __future__ import annotations

import pytest
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    plain = "Alice@2026"
    hashed = hash_password(plain)
    assert hashed != plain
    assert verify_password(plain, hashed) is True
    assert verify_password("wrong", hashed) is False


def test_access_and_refresh_token_roundtrip() -> None:
    access = create_access_token("00000000-0000-0000-0000-000000000001")
    refresh = create_refresh_token("00000000-0000-0000-0000-000000000001")

    payload_a = decode_token(access, expected_type="access")
    assert payload_a["type"] == "access"
    assert payload_a["sub"] == "00000000-0000-0000-0000-000000000001"

    payload_r = decode_token(refresh, expected_type="refresh")
    assert payload_r["type"] == "refresh"


def test_decode_with_wrong_type_raises() -> None:
    token = create_access_token("uid")
    with pytest.raises(TokenError):
        decode_token(token, expected_type="refresh")


def test_decode_garbage_raises() -> None:
    with pytest.raises(TokenError):
        decode_token("not-a-jwt")


async def test_health_endpoint(async_client) -> None:
    resp = await async_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_me_requires_auth(async_client) -> None:
    resp = await async_client.get("/api/me")
    assert resp.status_code == 401


async def test_register_then_me_flow(async_client) -> None:
    # 注册新用户
    reg = await async_client.post(
        "/api/auth/register",
        json={"username": "tester01", "password": "Tester@2026"},
    )
    assert reg.status_code == 201, reg.text

    # 登录拿 token
    login = await async_client.post(
        "/api/auth/login",
        json={"username": "tester01", "password": "Tester@2026"},
    )
    assert login.status_code == 200, login.text
    body = login.json()
    access = body["access_token"]

    # 用 token 调 /me
    me = await async_client.get("/api/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    assert me.json()["username"] == "tester01"


async def test_refresh_token_flow(async_client) -> None:
    # 自己注册，避免依赖其他测试的状态
    await async_client.post(
        "/api/auth/register",
        json={"username": "refresher", "password": "Refresher@2026"},
    )
    login = await async_client.post(
        "/api/auth/login",
        json={"username": "refresher", "password": "Refresher@2026"},
    )
    assert login.status_code == 200, login.text
    refresh = login.json()["refresh_token"]

    resp = await async_client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 200, resp.text
    assert "access_token" in resp.json()
