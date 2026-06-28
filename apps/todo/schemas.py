from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from apps.tags.schemas import TagResponse
from apps.todo.models import FrequencyEnum, PriorityEnum, StatusEnum


# ── Request schemas ──────────────────────────────────────────────────────────


class TodoCreate(BaseModel):
    title: str
    description: str | None = None
    priority: PriorityEnum = PriorityEnum.medium
    status: StatusEnum = StatusEnum.pending
    due_date: datetime | None = None
    parent_id: int | None = None
    is_reminder: bool = False


class TodoUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: PriorityEnum | None = None
    status: StatusEnum | None = None
    due_date: datetime | None = None
    is_reminder: bool | None = None


class SubtaskCreate(BaseModel):
    title: str
    description: str | None = None
    priority: PriorityEnum = PriorityEnum.medium


class RecurrenceCreate(BaseModel):
    frequency: FrequencyEnum
    interval: int = 1
    end_date: datetime | None = None


# ── Response schemas ─────────────────────────────────────────────────────────


class RecurrenceResponse(BaseModel):
    id: int
    frequency: str
    interval: int
    end_date: datetime | None
    next_occurrence: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TodoResponse(BaseModel):
    id: int
    user_id: int
    parent_id: int | None
    title: str
    description: str | None
    priority: str
    status: str
    due_date: datetime | None
    completed_at: datetime | None
    deleted_at: datetime | None
    is_reminder: bool
    created_at: datetime
    updated_at: datetime
    recurrence: RecurrenceResponse | None = None
    tags: list[TagResponse] = []
    subtasks: list[TodoResponse] = []

    model_config = {"from_attributes": True}
