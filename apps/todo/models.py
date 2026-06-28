from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class PriorityEnum(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class StatusEnum(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"


class FrequencyEnum(str, enum.Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


class Todo(Base):
    __tablename__ = "todos"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("todos.id"), nullable=True, default=None
    )
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    priority: Mapped[str] = mapped_column(
        String(10), default=PriorityEnum.medium.value
    )
    status: Mapped[str] = mapped_column(
        String(20), default=StatusEnum.pending.value
    )
    due_date: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
    is_reminder: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Self-referential: a todo can have many subtasks
    subtasks: Mapped[list[Todo]] = relationship(
        "Todo",
        foreign_keys="[Todo.parent_id]",
        lazy="selectin",
    )

    # One-to-one recurrence rule
    recurrence: Mapped[TodoRecurrence | None] = relationship(
        "TodoRecurrence",
        back_populates="todo",
        uselist=False,
        lazy="selectin",
    )


class TodoRecurrence(Base):
    __tablename__ = "todo_recurrence"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    todo_id: Mapped[int] = mapped_column(
        ForeignKey("todos.id"), unique=True, index=True
    )
    frequency: Mapped[str] = mapped_column(String(10))  # daily, weekly, monthly
    interval: Mapped[int] = mapped_column(Integer, default=1)  # every N
    end_date: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
    next_occurrence: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    todo: Mapped[Todo] = relationship("Todo", back_populates="recurrence")
