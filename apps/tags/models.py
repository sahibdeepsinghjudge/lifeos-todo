from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str] = mapped_column(String(7), default="#3b82f6")  # hex color
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    # Unique constraint: one tag name per user
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_user_tag_name"),)


class Taggable(Base):
    __tablename__ = "taggable"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), index=True
    )
    entity_type: Mapped[str] = mapped_column(String(50))  # 'todo', 'reminder', 'expense'
    entity_id: Mapped[int] = mapped_column(index=True)

    # Unique constraint: prevent duplicate tag assignment
    __table_args__ = (
        UniqueConstraint("tag_id", "entity_type", "entity_id", name="uq_taggable"),
    )
