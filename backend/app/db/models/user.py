"""用户与 LLM 配置。"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class UserRole(enum.StrEnum):
    ADMIN = "admin"
    USER = "user"

    # 防止 SQLAlchemy 把 enum name 当 value 使用
    def __init__(self, value: str) -> None:
        # str-Enum 默认行为正确，这里显式 override 让 IDE 也满意
        super().__init__()


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            name="user_role",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        default=UserRole.USER,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    token_budget: Mapped[int] = mapped_column(Integer, default=8000, nullable=False)

    llm_config: Mapped[LLMConfig | None] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )


class LLMConfig(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "llm_configs"
    __table_args__ = (UniqueConstraint("user_id", name="uq_llm_configs_user"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="openai_compatible")
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(String(1024), nullable=False)
    chat_model: Mapped[str] = mapped_column(String(128), nullable=False)
    embed_model: Mapped[str] = mapped_column(String(128), nullable=False)
    rerank_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embed_dim: Mapped[int] = mapped_column(Integer, default=1536, nullable=False)
    updated_at: Mapped[__import__('datetime').datetime] = mapped_column(  # noqa: F821
        __import__("sqlalchemy").DateTime(timezone=True),
        default=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        onupdate=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="llm_config")
