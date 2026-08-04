"""add reasoning to chat_messages

Revision ID: 0006_chat_reasoning
Revises: 0005_memory_events
Create Date: 2026-08-04

阶段 6：thinking 渲染存单独字段。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_chat_reasoning"
down_revision: str | None = "0005_memory_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("reasoning", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "reasoning")
