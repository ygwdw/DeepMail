"""users.token_budget: per-user chat context window

Revision ID: 0007_token_budget
Revises: 0006_chat_reasoning
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_token_budget"
down_revision: str | None = "0006_chat_reasoning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_budget", sa.Integer, nullable=False, server_default="8000"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_budget")
