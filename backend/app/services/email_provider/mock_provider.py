"""Mock Email Provider：从 data/mock_emails/*.json 读取。"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings, resolve_path
from app.services.email_provider.base import EmailPayload, EmailProvider

_settings = get_settings()


class MockEmailProvider(EmailProvider):
    """内存版 Mock：启动时一次性加载所有 JSON 文件。"""

    name = "mock"

    def __init__(self, mock_dir: str | Path | None = None) -> None:
        if mock_dir is None:
            self._dir = resolve_path(_settings.mock_emails_dir)
        else:
            p = Path(mock_dir)
            self._dir = p if p.is_absolute() else resolve_path(str(p))
        self._emails: dict[str, EmailPayload] = {}
        self._user_index: dict[uuid.UUID, list[str]] = {}
        self._load()

    def _load(self) -> None:
        if not self._dir.exists():
            return
        for fp in sorted(self._dir.glob("*.json")):
            with fp.open("r", encoding="utf-8") as f:
                raw_list: list[dict[str, Any]] = json.load(f)
            for raw in raw_list:
                payload = self._parse(raw)
                self._emails[payload.message_id] = payload

        # 同一个 mock 库"分配"给每个用户（演示阶段不区分）
        # 真用户登录后通过 seed 把所有邮件 copy 到其 user_id 命名空间
        for mid in self._emails:
            pass

    def _parse(self, raw: dict[str, Any]) -> EmailPayload:
        recipients = raw.get("recipients", [])
        cc = raw.get("cc", [])
        labels = raw.get("labels", [])
        categories = raw.get("categories", [])
        return EmailPayload(
            message_id=raw["message_id"],
            sender_name=(
                raw.get("sender", "").split(" <")[0] if "<" in raw.get("sender", "") else None
            ),
            sender_email=_extract_email(raw.get("sender", "")),
            recipients=recipients,
            cc=cc,
            subject=raw.get("subject", ""),
            body_text=raw.get("body_text", ""),
            body_html=raw.get("body_html"),
            sent_at=_to_dt(raw["sent_at"]),
            received_at=_to_dt(raw.get("received_at") or raw["sent_at"]),
            thread_id=raw.get("thread_id"),
            labels=labels,
            categories=categories,
            raw_payload=raw,
        )

    # --- EmailProvider 接口 ---

    async def list_emails(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EmailPayload]:
        all_emails = sorted(
            self._emails.values(),
            key=lambda e: e.received_at,
            reverse=True,
        )
        return all_emails[offset : offset + limit]

    async def get_email(
        self,
        user_id: uuid.UUID,
        message_id: str,
    ) -> EmailPayload | None:
        return self._emails.get(message_id)

    async def send_email(
        self,
        user_id: uuid.UUID,
        *,
        to: list[str],
        subject: str,
        body_text: str,
        body_html: str | None = None,
    ) -> EmailPayload:
        now = datetime.now(UTC)
        new_id = f"<msg-{uuid.uuid4().hex[:8]}@mock.local>"
        payload = EmailPayload(
            message_id=new_id,
            sender_name="user",
            sender_email="user@deepmail.local",
            recipients=to,
            cc=[],
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            sent_at=now,
            received_at=now,
            thread_id=None,
            labels=[],
            categories=[],
            raw_payload={"sent_by": "mock_provider", "user_id": str(user_id)},
        )
        self._emails[new_id] = payload
        return payload

    async def delete_email(self, user_id: uuid.UUID, message_id: str) -> None:
        self._emails.pop(message_id, None)

    async def mark_read(self, user_id: uuid.UUID, message_id: str, *, is_read: bool) -> None:
        # Mock 实现不持久化已读标记；上层写回 DB 即可
        return None


def _extract_email(sender_str: str) -> str:
    if "<" in sender_str and ">" in sender_str:
        return sender_str.split("<")[1].split(">")[0].strip()
    return sender_str.strip()


def _to_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)
