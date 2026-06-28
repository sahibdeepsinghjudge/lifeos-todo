"""FastAPI router for the Todo module."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.todo import service
from apps.todo.models import Todo
from apps.todo.schemas import (
    RecurrenceCreate,
    RecurrenceResponse,
    SubtaskCreate,
    TodoCreate,
    TodoResponse,
    TodoUpdate,
)
from core.database import get_db
from core.security import get_current_user

router = APIRouter(prefix="/todos", tags=["Todos"])


# ── Response helpers ─────────────────────────────────────────────────────────


def _todo_to_response(db: Session, todo: Todo) -> TodoResponse:
    """Convert a Todo ORM object to a TodoResponse, attaching tags."""
    tags = service.get_tags_for_todo(db, todo.id)

    subtask_responses = [
        _todo_to_response(db, child)
        for child in (todo.subtasks or [])
        if child.deleted_at is None
    ]

    return TodoResponse.model_validate(
        {
            "id": todo.id,
            "user_id": todo.user_id,
            "parent_id": todo.parent_id,
            "title": todo.title,
            "description": todo.description,
            "priority": todo.priority,
            "status": todo.status,
            "due_date": todo.due_date,
            "completed_at": todo.completed_at,
            "deleted_at": todo.deleted_at,
            "created_at": todo.created_at,
            "updated_at": todo.updated_at,
            "is_reminder": todo.is_reminder,
            "recurrence": todo.recurrence,
            "tags": tags,
            "subtasks": subtask_responses,
        }
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TodoResponse)
def create_todo(
    data: TodoCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    todo = service.create_todo(db, user.id, data)
    return _todo_to_response(db, todo)


@router.get("", response_model=list[TodoResponse])
def list_todos(
    status_filter: str | None = Query(None, alias="status"),
    priority: str | None = None,
    tag: str | None = None,
    due_before: datetime | None = None,
    due_after: datetime | None = None,
    search: str | None = None,
    overdue: bool = False,
    is_reminder: bool | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    todos = service.list_todos(
        db,
        user.id,
        status_filter=status_filter,
        priority=priority,
        tag=tag,
        due_before=due_before,
        due_after=due_after,
        search=search,
        overdue=overdue,
        is_reminder=is_reminder,
    )
    return [_todo_to_response(db, t) for t in todos]


@router.get("/{todo_id}", response_model=TodoResponse)
def get_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    todo = service.get_todo(db, user.id, todo_id)
    return _todo_to_response(db, todo)


@router.put("/{todo_id}", response_model=TodoResponse)
def update_todo(
    todo_id: int,
    data: TodoUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    todo = service.update_todo(db, user.id, todo_id, data)
    return _todo_to_response(db, todo)


@router.delete("/{todo_id}")
def delete_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    service.delete_todo(db, user.id, todo_id)
    return {"detail": "Todo deleted"}


# ── Subtasks ─────────────────────────────────────────────────────────────────


@router.post(
    "/{todo_id}/subtasks",
    status_code=status.HTTP_201_CREATED,
    response_model=TodoResponse,
)
def create_subtask(
    todo_id: int,
    data: SubtaskCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    child = service.create_subtask(db, user.id, todo_id, data)
    return _todo_to_response(db, child)


@router.get("/{todo_id}/subtasks", response_model=list[TodoResponse])
def list_subtasks(
    todo_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    subtasks = service.list_subtasks(db, user.id, todo_id)
    return [_todo_to_response(db, s) for s in subtasks]


# ── Completion ───────────────────────────────────────────────────────────────


@router.post("/{todo_id}/complete", response_model=dict)
def complete_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    result = service.complete_todo(db, user.id, todo_id)
    response: dict = {"todo": _todo_to_response(db, result["todo"])}
    if result["next_occurrence"] is not None:
        response["next_occurrence"] = _todo_to_response(
            db, result["next_occurrence"]
        )
    else:
        response["next_occurrence"] = None
    return response


# ── Recurrence ───────────────────────────────────────────────────────────────


@router.post(
    "/{todo_id}/recurrence",
    status_code=status.HTTP_201_CREATED,
    response_model=RecurrenceResponse,
)
def set_recurrence(
    todo_id: int,
    data: RecurrenceCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return service.set_recurrence(db, user.id, todo_id, data)


@router.delete("/{todo_id}/recurrence")
def delete_recurrence(
    todo_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    service.delete_recurrence(db, user.id, todo_id)
    return {"detail": "Recurrence removed"}


# ── Tags ─────────────────────────────────────────────────────────────────────


@router.post(
    "/{todo_id}/tags/{tag_id}",
    status_code=status.HTTP_201_CREATED,
)
def add_tag(
    todo_id: int,
    tag_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    service.add_tag_to_todo(db, user.id, todo_id, tag_id)
    return {"detail": "Tag added"}


@router.delete("/{todo_id}/tags/{tag_id}")
def remove_tag(
    todo_id: int,
    tag_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    service.remove_tag_from_todo(db, user.id, todo_id, tag_id)
    return {"detail": "Tag removed"}
