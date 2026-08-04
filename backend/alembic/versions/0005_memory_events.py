"""memory layer 6-level schema (L3 events + L4 categories)

Revision ID: 0005_memory_events
Revises: 0004_embed_dim_1024
Create Date: 2026-08-04

按 develop_doc/记忆系统重新设计.md：
- L3 事件：events + event_timeline 两表
- L4 语义：memory_long_term 加 category 字段（v1 暂不用统一存 JSONB）
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_memory_events"
down_revision: str | None = "0004_embed_dim_1024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # L3 事件主表
    op.create_table(
        "memory_events",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_memory_events_user_id", "memory_events", ["user_id"])
    op.create_index("ix_memory_events_status", "memory_events", ["status"])

    # L3 事件时间线（每条事件的时间线点）
    op.create_table(
        "memory_event_timeline",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False, server_default="note"),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("source_ref", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["memory_events.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_memory_event_timeline_event_id", "memory_event_timeline", ["event_id"])
    op.create_index(
        "ix_memory_event_timeline_occurred_at", "memory_event_timeline", ["occurred_at"]
    )

    # L4 语义记忆：category 字段（v1 可选填）
    op.add_column(
        "memory_long_term",
        sa.Column("category", sa.String(64), nullable=False, server_default="misc"),
    )
    op.create_index("ix_memory_long_term_category", "memory_long_term", ["category"])


def downgrade() -> None:
    op.drop_index("ix_memory_long_term_category", table_name="memory_long_term")
    op.drop_column("memory_long_term", "category")

    op.drop_index("ix_memory_event_timeline_occurred_at", table_name="memory_event_timeline")
    op.drop_index("ix_memory_event_timeline_event_id", table_name="memory_event_timeline")
    op.drop_table("memory_event_timeline")

    op.drop_index("ix_memory_events_status", table_name="memory_events")
    op.drop_index("ix_memory_events_user_id", table_name="memory_events")
    op.drop_table("memory_events")
