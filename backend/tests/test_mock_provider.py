"""Mock Email Provider 单测。"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from app.services.email_provider.mock_provider import MockEmailProvider


@pytest.fixture
def provider() -> MockEmailProvider:
    return MockEmailProvider(mock_dir=str(Path("data/mock_emails").resolve()))


async def test_loads_30_emails(provider: MockEmailProvider) -> None:
    emails = await provider.list_emails(uuid.uuid4(), limit=200)
    assert len(emails) == 30


async def test_list_ordered_desc(provider: MockEmailProvider) -> None:
    emails = await provider.list_emails(uuid.uuid4(), limit=200)
    times = [e.received_at for e in emails]
    assert times == sorted(times, reverse=True)


async def test_get_email(provider: MockEmailProvider) -> None:
    sample = await provider.get_email(uuid.uuid4(), "<msg-001@verification.example.com>")
    assert sample is not None
    assert sample.sender_email.endswith("@cmbchina.com")
    assert "验证码" in sample.subject


async def test_send_email_persists(provider: MockEmailProvider) -> None:
    payload = await provider.send_email(
        uuid.uuid4(),
        to=["foo@example.com"],
        subject="hello",
        body_text="world",
    )
    again = await provider.get_email(uuid.uuid4(), payload.message_id)
    assert again is not None
    assert again.subject == "hello"


async def test_delete_email(provider: MockEmailProvider) -> None:
    user_id = uuid.uuid4()
    target = "<msg-001@verification.example.com>"
    await provider.delete_email(user_id, target)
    assert await provider.get_email(user_id, target) is None
