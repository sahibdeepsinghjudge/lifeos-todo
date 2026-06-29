"""Business logic for todo CRUD, subtasks, recurrence, and tagging."""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_
from sqlalchemy.orm import Session

from core.config import IST

from apps.tags.models import Tag, Taggable
from apps.todo.models import (
    FrequencyEnum,
    StatusEnum,
    Todo,
    TodoRecurrence,
)
from apps.todo.schemas import RecurrenceCreate, SubtaskCreate, TodoCreate, TodoUpdate


# ── Helpers ──────────────────────────────────────────────────────────────────


def _add_months(dt: datetime, months: int) -> datetime:
    """Return *dt* shifted forward by *months* calendar months."""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def get_tags_for_todo(db: Session, todo_id: int) -> list[Tag]:
    """Return all Tag objects linked to a given todo."""
    return (
        db.query(Tag)
        .join(Taggable, Taggable.tag_id == Tag.id)
        .filter(
            Taggable.entity_type == "todo",
            Taggable.entity_id == todo_id,
        )
        .all()
    )


def _get_todo_or_404(
    db: Session,
    user_id: int,
    todo_id: int,
    *,
    allow_deleted: bool = False,
) -> Todo:
    """Fetch a todo by id + user ownership, raise 404 on miss."""
    query = db.query(Todo).filter(Todo.id == todo_id, Todo.user_id == user_id)
    if not allow_deleted:
        query = query.filter(Todo.deleted_at.is_(None))
    todo = query.first()
    if todo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested task could not be found.",
        )
    return todo


# ── CRUD ─────────────────────────────────────────────────────────────────────


def create_todo(db: Session, user_id: int, data: TodoCreate) -> Todo:
    """Create a new top-level todo (or subtask via data.parent_id)."""
    if data.parent_id is not None:
        parent = _get_todo_or_404(db, user_id, data.parent_id)
        if parent.parent_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You can only add subtasks to top-level tasks, not to other subtasks.",
            )

    todo = Todo(
        user_id=user_id,
        parent_id=data.parent_id,
        title=data.title,
        description=data.description,
        priority=data.priority.value,
        status=data.status.value,
        due_date=data.due_date,
        is_reminder=data.is_reminder,
    )
    db.add(todo)
    db.commit()
    db.refresh(todo)
    return todo


def list_todos(
    db: Session,
    user_id: int,
    *,
    status_filter: str | None = None,
    priority: str | None = None,
    tag: str | None = None,
    due_before: datetime | None = None,
    due_after: datetime | None = None,
    search: str | None = None,
    overdue: bool = False,
    is_reminder: bool | None = None,
) -> list[Todo]:
    """Return top-level, non-deleted todos with optional filters."""
    query = db.query(Todo).filter(
        Todo.user_id == user_id,
        Todo.deleted_at.is_(None),
        Todo.parent_id.is_(None),
    )

    if is_reminder is not None:
        query = query.filter(Todo.is_reminder == is_reminder)

    if status_filter:
        query = query.filter(Todo.status == status_filter)

    if priority:
        query = query.filter(Todo.priority == priority)

    if tag:
        query = (
            query.join(Taggable, and_(
                Taggable.entity_type == "todo",
                Taggable.entity_id == Todo.id,
            ))
            .join(Tag, Tag.id == Taggable.tag_id)
            .filter(Tag.name == tag)
        )

    if due_before:
        query = query.filter(Todo.due_date <= due_before)

    if due_after:
        query = query.filter(Todo.due_date >= due_after)

    if search:
        query = query.filter(Todo.title.ilike(f"%{search}%"))

    if overdue:
        now = datetime.now(IST)
        query = query.filter(
            Todo.due_date < now,
            Todo.status != StatusEnum.completed.value,
        )

    return query.order_by(Todo.created_at.desc()).all()


def get_todo(db: Session, user_id: int, todo_id: int) -> Todo:
    """Get a single non-deleted todo owned by the user."""
    return _get_todo_or_404(db, user_id, todo_id)


def update_todo(db: Session, user_id: int, todo_id: int, data: TodoUpdate) -> Todo:
    """Partially update a todo with only the supplied fields."""
    todo = _get_todo_or_404(db, user_id, todo_id)

    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        if value is not None and hasattr(value, "value"):
            # Convert enum to its string value
            value = value.value
        setattr(todo, field, value)

    todo.updated_at = datetime.now(IST)
    db.commit()
    db.refresh(todo)
    return todo


def delete_todo(db: Session, user_id: int, todo_id: int) -> None:
    """Soft-delete a todo and all its subtasks."""
    todo = _get_todo_or_404(db, user_id, todo_id)
    now = datetime.now(IST)
    todo.deleted_at = now

    # Cascade soft-delete to subtasks
    subtasks = (
        db.query(Todo)
        .filter(Todo.parent_id == todo_id, Todo.deleted_at.is_(None))
        .all()
    )
    for child in subtasks:
        child.deleted_at = now

    db.commit()


# ── Subtasks ─────────────────────────────────────────────────────────────────


def create_subtask(
    db: Session, user_id: int, parent_id: int, data: SubtaskCreate
) -> Todo:
    """Create a subtask under an existing top-level todo."""
    parent = _get_todo_or_404(db, user_id, parent_id)
    if parent.parent_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subtasks can only be one level deep",
        )

    child = Todo(
        user_id=user_id,
        parent_id=parent_id,
        title=data.title,
        description=data.description,
        priority=data.priority.value,
        status=StatusEnum.pending.value,
    )
    db.add(child)
    db.commit()
    db.refresh(child)
    return child


def list_subtasks(db: Session, user_id: int, parent_id: int) -> list[Todo]:
    """Return non-deleted subtasks of a given parent todo."""
    _get_todo_or_404(db, user_id, parent_id)
    return (
        db.query(Todo)
        .filter(
            Todo.parent_id == parent_id,
            Todo.deleted_at.is_(None),
        )
        .order_by(Todo.created_at.asc())
        .all()
    )


# ── Completion & Recurrence ─────────────────────────────────────────────────


def complete_todo(
    db: Session, user_id: int, todo_id: int
) -> dict:
    """Mark a todo as completed; if recurring, spawn the next occurrence."""
    todo = _get_todo_or_404(db, user_id, todo_id)
    todo.status = StatusEnum.completed.value
    todo.completed_at = datetime.now(IST)
    todo.updated_at = datetime.now(IST)

    next_todo: Todo | None = None
    if todo.recurrence is not None:
        next_todo = _create_next_occurrence(db, todo, todo.recurrence)

    db.commit()
    if next_todo is not None:
        db.refresh(next_todo)
    db.refresh(todo)
    return {"todo": todo, "next_occurrence": next_todo}


def _create_next_occurrence(
    db: Session, todo: Todo, recurrence: TodoRecurrence
) -> Todo | None:
    """Clone the completed todo with a new due date based on recurrence rules."""
    base_date = todo.due_date or datetime.now(IST)

    if recurrence.frequency == FrequencyEnum.daily.value:
        next_date = base_date + timedelta(days=recurrence.interval)
    elif recurrence.frequency == FrequencyEnum.weekly.value:
        next_date = base_date + timedelta(weeks=recurrence.interval)
    elif recurrence.frequency == FrequencyEnum.monthly.value:
        next_date = _add_months(base_date, recurrence.interval)
    else:
        return None

    # Respect end_date boundary
    if recurrence.end_date is not None and next_date > recurrence.end_date:
        return None

    # Check if a task with the exact title already exists for this date
    existing_next = (
        db.query(Todo)
        .filter(
            Todo.user_id == todo.user_id,
            Todo.title == todo.title,
            Todo.due_date == next_date,
            Todo.deleted_at.is_(None)
        )
        .first()
    )

    if existing_next:
        # Link recurrence to existing task if missing
        if not existing_next.recurrence:
            new_recurrence = TodoRecurrence(
                todo_id=existing_next.id,
                frequency=recurrence.frequency,
                interval=recurrence.interval,
                end_date=recurrence.end_date,
                next_occurrence=next_date,
            )
            db.add(new_recurrence)
        recurrence.next_occurrence = next_date
        new_todo = existing_next
    else:
        # Clone the todo
        new_todo = Todo(
            user_id=todo.user_id,
            title=todo.title,
            description=todo.description,
            priority=todo.priority,
            status=StatusEnum.pending.value,
            due_date=next_date,
            is_reminder=todo.is_reminder,
        )
        db.add(new_todo)
        db.flush()  # get new_todo.id before creating recurrence

        # Clone the recurrence rule
        new_recurrence = TodoRecurrence(
            todo_id=new_todo.id,
            frequency=recurrence.frequency,
            interval=recurrence.interval,
            end_date=recurrence.end_date,
            next_occurrence=next_date,
        )
        db.add(new_recurrence)

        # Update old recurrence pointer
        recurrence.next_occurrence = next_date

        # Clone tags from the original todo
        taggables = (
            db.query(Taggable)
            .filter(Taggable.entity_type == "todo", Taggable.entity_id == todo.id)
            .all()
        )
        for t in taggables:
            db.add(
                Taggable(
                    tag_id=t.tag_id,
                    entity_type="todo",
                    entity_id=new_todo.id,
                )
            )

    # Clone subtasks if new_todo doesn't have them yet
    existing_subtasks_count = (
        db.query(Todo)
        .filter(Todo.parent_id == new_todo.id, Todo.deleted_at.is_(None))
        .count()
    )

    if existing_subtasks_count == 0:
        subtasks = (
            db.query(Todo)
            .filter(Todo.parent_id == todo.id, Todo.deleted_at.is_(None))
            .all()
        )
        for child in subtasks:
            child_due_date = child.due_date
            if child_due_date:
                if recurrence.frequency == FrequencyEnum.daily.value:
                    child_due_date += timedelta(days=recurrence.interval)
                elif recurrence.frequency == FrequencyEnum.weekly.value:
                    child_due_date += timedelta(weeks=recurrence.interval)
                elif recurrence.frequency == FrequencyEnum.monthly.value:
                    child_due_date = _add_months(child_due_date, recurrence.interval)

            db.add(
                Todo(
                    user_id=child.user_id,
                    parent_id=new_todo.id,
                    title=child.title,
                    description=child.description,
                    priority=child.priority,
                    status=StatusEnum.pending.value,
                    due_date=child_due_date,
                    is_reminder=child.is_reminder,
                )
            )

    return new_todo


def set_recurrence(
    db: Session, user_id: int, todo_id: int, data: RecurrenceCreate
) -> TodoRecurrence:
    """Attach a recurrence rule to a todo (one per todo)."""
    todo = _get_todo_or_404(db, user_id, todo_id)
    if todo.recurrence is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recurrence already exists for this todo",
        )

    base_date = todo.due_date or datetime.now(IST)
    if data.frequency == FrequencyEnum.daily:
        next_occ = base_date + timedelta(days=data.interval)
    elif data.frequency == FrequencyEnum.weekly:
        next_occ = base_date + timedelta(weeks=data.interval)
    else:
        next_occ = _add_months(base_date, data.interval)

    recurrence = TodoRecurrence(
        todo_id=todo.id,
        frequency=data.frequency.value,
        interval=data.interval,
        end_date=data.end_date,
        next_occurrence=next_occ,
    )
    db.add(recurrence)
    db.commit()
    db.refresh(recurrence)
    return recurrence


def delete_recurrence(db: Session, user_id: int, todo_id: int) -> None:
    """Remove the recurrence rule from a todo."""
    todo = _get_todo_or_404(db, user_id, todo_id)
    if todo.recurrence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No recurrence found for this todo",
        )
    db.delete(todo.recurrence)
    db.commit()


# ── Tagging ──────────────────────────────────────────────────────────────────


def add_tag_to_todo(
    db: Session, user_id: int, todo_id: int, tag_id: int
) -> None:
    """Link a tag to a todo, ignoring duplicates."""
    _get_todo_or_404(db, user_id, todo_id)

    tag = db.query(Tag).filter(Tag.id == tag_id, Tag.user_id == user_id).first()
    if tag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found",
        )

    existing = (
        db.query(Taggable)
        .filter(
            Taggable.tag_id == tag_id,
            Taggable.entity_type == "todo",
            Taggable.entity_id == todo_id,
        )
        .first()
    )
    if existing is not None:
        return  # already tagged, nothing to do

    db.add(
        Taggable(tag_id=tag_id, entity_type="todo", entity_id=todo_id)
    )
    db.commit()


def remove_tag_from_todo(
    db: Session, user_id: int, todo_id: int, tag_id: int
) -> None:
    """Unlink a tag from a todo."""
    _get_todo_or_404(db, user_id, todo_id)

    taggable = (
        db.query(Taggable)
        .filter(
            Taggable.tag_id == tag_id,
            Taggable.entity_type == "todo",
            Taggable.entity_id == todo_id,
        )
        .first()
    )
    if taggable is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not attached to this todo",
        )
    db.delete(taggable)
    db.commit()
