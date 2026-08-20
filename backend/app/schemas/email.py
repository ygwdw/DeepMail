"""邮件相关 DTO。"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.schemas.common import ORMModel


class EmailRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    message_id: str
    thread_id: str | None
    sender_name: str | None
    sender_email: str
    recipients: list[str]
    cc: list[str]
    subject: str
    body_text: str
    sent_at: datetime
    received_at: datetime
    is_read: bool
    spam_score: float
    folder: str
    labels: list[str]
    categories: list[str]
    summary: str | None
    # v2-M9 / bug fix: 详情页要展示待办；之前 schema 缺这个字段导致详情页 todos 显示空
    todos_extracted: list[dict] = []
    entities_extracted: list[dict] = []


def make_body_preview(body: str | None, max_chars: int = 150) -> str:
    """生成列表预览文本：去多余空白 + 截断到 max_chars。"""
    if not body:
        return ""
    text = " ".join(body.split())  # 合并空白 + 换行
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


class EmailListItem(ORMModel):
    """列表用的精简视图（不含正文）。"""

    id: uuid.UUID
    message_id: str
    thread_id: str | None
    sender_name: str | None
    sender_email: str
    subject: str
    sent_at: datetime
    received_at: datetime
    is_read: bool
    spam_score: float
    folder: str
    labels: list[str]
    categories: list[str]
    summary: str | None
    # v2-M6：列表 hover 显示待办；带 label/category 必须能看到
    todos_extracted: list[dict] = []
    # v2-M6 增量：邮件正文预览（前 150 字，用于列表卡片）
    body_preview: str = ""
