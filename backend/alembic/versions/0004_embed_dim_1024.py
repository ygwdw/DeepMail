"""change embedding dim to 1024 (Qwen3-Embedding-0.6B)"

Revision ID: 0004_embed_dim_1024
Revises: 0003_add_descriptions
Create Date: 2026-08-03

切到 Qwen3-Embedding-0.6B，维度 1536 → 1024。
pgvector 的 vector(N) 列宽是固定的，必须 drop + recreate。
阶段 2 起步阶段数据量小，直接清空是合理的；后续会有非破坏迁移工具。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0004_embed_dim_1024"
down_revision: str | None = "0003_add_descriptions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_DIM = 1024


def upgrade() -> None:
    # knowledge_chunks.embedding + entities.embedding: drop & recreate
    op.drop_column("knowledge_chunks", "embedding")
    op.add_column(
        "knowledge_chunks",
        sa.Column("embedding", Vector(NEW_DIM), nullable=True),
    )
    op.drop_column("entities", "embedding")
    op.add_column(
        "entities",
        sa.Column("embedding", Vector(NEW_DIM), nullable=True),
    )
    # memory_medium_topics.embedding
    op.drop_column("memory_medium_topics", "embedding")
    op.add_column(
        "memory_medium_topics",
        sa.Column("embedding", Vector(NEW_DIM), nullable=True),
    )


def downgrade() -> None:
    OLD_DIM = 1536
    op.drop_column("knowledge_chunks", "embedding")
    op.add_column(
        "knowledge_chunks",
        sa.Column("embedding", Vector(OLD_DIM), nullable=True),
    )
    op.drop_column("entities", "embedding")
    op.add_column(
        "entities",
        sa.Column("embedding", Vector(OLD_DIM), nullable=True),
    )
    op.drop_column("memory_medium_topics", "embedding")
    op.add_column(
        "memory_medium_topics",
        sa.Column("embedding", Vector(OLD_DIM), nullable=True),
    )
