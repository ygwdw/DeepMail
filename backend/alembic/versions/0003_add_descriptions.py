"""add descriptions to categories and labels

Revision ID: 0003_add_descriptions
Revises: 0002_ai_phase1
Create Date: 2026-08-03

用户可对分类 / 标签添加描述，帮助 LLM 更好理解分类和打标。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_add_descriptions"
down_revision: str | None = "0002_ai_phase1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "categories",
        sa.Column("description", sa.Text, nullable=False, server_default=""),
    )
    op.add_column(
        "labels",
        sa.Column("description", sa.Text, nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("labels", "description")
    op.drop_column("categories", "description")
