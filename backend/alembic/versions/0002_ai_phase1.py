"""ai phase1 schema additions

Revision ID: 0002_ai_phase1
Revises: 0001_initial
Create Date: 2026-08-03

Changes:
- emails.folder        (inbox/sent/spam/trash)
- categories.is_spam_category
- usage_logs table
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_ai_phase1"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "emails",
        sa.Column(
            "folder",
            sa.String(16),
            nullable=False,
            server_default="inbox",
        ),
    )
    op.create_index("ix_emails_folder", "emails", ["folder"])

    op.add_column(
        "categories",
        sa.Column(
            "is_spam_category",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "usage_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("skill_name", sa.String(64), nullable=False),
        sa.Column(
            "email_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("emails.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tokens_prompt", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_completion", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_usage_logs_user_id", "usage_logs", ["user_id"])
    op.create_index("ix_usage_logs_skill_name", "usage_logs", ["skill_name"])
    op.create_index("ix_usage_logs_created_at", "usage_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_usage_logs_created_at", table_name="usage_logs")
    op.drop_index("ix_usage_logs_skill_name", table_name="usage_logs")
    op.drop_index("ix_usage_logs_user_id", table_name="usage_logs")
    op.drop_table("usage_logs")

    op.drop_column("categories", "is_spam_category")

    op.drop_index("ix_emails_folder", table_name="emails")
    op.drop_column("emails", "folder")
