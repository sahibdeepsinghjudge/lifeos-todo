"""RAG context builder — retrieves the user's tasks and preferences up front.

The assistant is grounded in this snapshot instead of having to discover the
user's data through tool calls, so most questions ("what's my day look like?",
"what's overdue?") can be answered directly from the prompt.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from core.config import IST
from apps.todo import service as todo_service
from apps.todo.models import Todo
from apps.tags.service import list_tags

# Cap per bucket so a heavy user can't blow up the prompt
MAX_TODOS_PER_BUCKET = 15


def _format_todo(todo: Todo) -> str:
    parts = [f"[id {todo.id}] {todo.title}"]
    details = [todo.priority, todo.status]
    if todo.due_date:
        details.append(f"due {todo.due_date.strftime('%Y-%m-%d %H:%M')}")
    if todo.is_reminder:
        details.append("reminder")
    subtasks = [s for s in (todo.subtasks or []) if s.deleted_at is None]
    if subtasks:
        done = sum(1 for s in subtasks if s.status == "completed")
        details.append(f"{done}/{len(subtasks)} subtasks done")
    parts.append(f"({', '.join(details)})")
    return " ".join(parts)


def _format_bucket(title: str, todos: list[Todo]) -> str:
    if not todos:
        return f"{title}: none"
    lines = [f"{title}:"]
    for todo in todos[:MAX_TODOS_PER_BUCKET]:
        lines.append(f"  - {_format_todo(todo)}")
    if len(todos) > MAX_TODOS_PER_BUCKET:
        lines.append(f"  - ...and {len(todos) - MAX_TODOS_PER_BUCKET} more")
    return "\n".join(lines)


def build_user_context(db: Session, user_id: int, user_prefs: str | None) -> str:
    """Build the grounding block injected into the assistant's system prompt."""
    now = datetime.now(IST).replace(tzinfo=None)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    week_end = today_start + timedelta(days=8)

    pending = todo_service.list_todos(db, user_id, status_filter="pending")
    in_progress = todo_service.list_todos(db, user_id, status_filter="in_progress")
    open_todos = pending + in_progress

    overdue = [t for t in open_todos if t.due_date and t.due_date < now]
    today = [t for t in open_todos if t.due_date and today_start <= t.due_date < today_end and t not in overdue]
    upcoming = [t for t in open_todos if t.due_date and today_end <= t.due_date < week_end]
    unscheduled = [t for t in open_todos if not t.due_date]

    completed = todo_service.list_todos(db, user_id, status_filter="completed")
    completed_today = [t for t in completed if t.completed_at and t.completed_at >= today_start]

    sections = [
        _format_bucket("Overdue tasks", sorted(overdue, key=lambda t: t.due_date)),
        _format_bucket("Today's tasks", sorted(today, key=lambda t: t.due_date)),
        _format_bucket("Upcoming (next 7 days)", sorted(upcoming, key=lambda t: t.due_date)),
        _format_bucket("Unscheduled tasks", unscheduled),
        f"Completed today: {len(completed_today)}",
    ]

    tags = list_tags(db, user_id)
    if tags:
        sections.append("Existing tags: " + ", ".join(t.name for t in tags))

    if user_prefs:
        try:
            prefs = json.loads(user_prefs)
            if prefs:
                lines = ["Saved user preferences:"]
                lines += [f"  - {k}: {v}" for k, v in prefs.items()]
                sections.append("\n".join(lines))
        except json.JSONDecodeError:
            sections.append(f"Saved user preferences: {user_prefs}")

    return "\n\n".join(sections)
