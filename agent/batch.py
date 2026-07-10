"""Batch execution + deterministic summaries for the plan-then-execute flow.

The assistant emits a single `apply_todo_changes` call describing every change
at once; we run each item here (reusing the granular tool handlers so all the
parsing/coercion stays in one place), collect per-item outcomes, and turn them
into a human summary WITHOUT another LLM round-trip. Individual failures are
captured, never raised — one bad item can't sink the rest of the batch.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from agent.handlers import handle_tool_call

logger = logging.getLogger(__name__)

# Zeroed template so summarize_counts can rely on every key existing.
_ZERO_COUNTS = {
    "created": 0,
    "updated": 0,
    "completed": 0,
    "deleted": 0,
    "recurring": 0,
    "tagged": 0,
    "subtasks": 0,
    "context": 0,
}

# Granular write tool -> which counter it increments on success.
GRANULAR_COUNT_KEY = {
    "create_todo": "created",
    "update_todo": "updated",
    "complete_todo": "completed",
    "delete_todo": "deleted",
    "set_recurrence": "recurring",
    "add_tag_to_todo": "tagged",
    "create_subtask": "subtasks",
    "save_user_context": "context",
    "delete_user_context": "context",
}


def _run(db: Session, user_id: int, tool: str, args: dict) -> tuple[bool, dict]:
    """Run one granular tool. Returns (ok, parsed_result). Never raises."""
    try:
        raw = handle_tool_call(tool, dict(args), db, user_id)
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and parsed.get("error"):
            return False, parsed
        return True, parsed if isinstance(parsed, dict) else {"result": parsed}
    except Exception as e:  # noqa: BLE001 — batch item errors are collected, not fatal
        logger.error("batch item '%s' failed: %s (args=%s)", tool, e, args)
        return False, {"error": str(e)}


def apply_changes(db: Session, user_id: int, batch: dict) -> dict:
    """Apply a batch of todo changes. Returns {"counts": {...}, "errors": [...]}."""
    counts = dict(_ZERO_COUNTS)
    errors: list[str] = []

    def note_error(msg: str, res: dict) -> None:
        errors.append(f"{msg}: {res.get('error', 'failed')}")

    # ── creates (with optional nested recurrence / subtasks) ──────────────
    for item in batch.get("create") or []:
        if not isinstance(item, dict):
            continue
        item = dict(item)
        recurrence = item.pop("recurrence", None)
        subtasks = item.pop("subtasks", None)
        ok, res = _run(db, user_id, "create_todo", item)
        if not ok:
            note_error(f"create '{item.get('title', '?')}'", res)
            continue
        counts["created"] += 1
        todo_id = res.get("id")
        if recurrence and todo_id:
            r = dict(recurrence)
            r["todo_id"] = todo_id
            ok2, res2 = _run(db, user_id, "set_recurrence", r)
            if ok2:
                counts["recurring"] += 1
            else:
                note_error(f"recurrence for '{item.get('title', '?')}'", res2)
        for st in subtasks or []:
            ok3, res3 = _run(
                db, user_id, "create_subtask", {"parent_todo_id": todo_id, "title": st}
            )
            if ok3:
                counts["subtasks"] += 1
            else:
                note_error(f"subtask '{st}'", res3)

    # ── updates ───────────────────────────────────────────────────────────
    for item in batch.get("update") or []:
        if not isinstance(item, dict):
            continue
        ok, res = _run(db, user_id, "update_todo", item)
        if ok:
            counts["updated"] += 1
        else:
            note_error(f"update #{item.get('todo_id', '?')}", res)

    # ── completes ─────────────────────────────────────────────────────────
    for tid in batch.get("complete") or []:
        ok, res = _run(db, user_id, "complete_todo", {"todo_id": tid})
        if ok:
            counts["completed"] += 1
        else:
            note_error(f"complete #{tid}", res)

    # ── deletes ───────────────────────────────────────────────────────────
    for tid in batch.get("delete") or []:
        ok, res = _run(db, user_id, "delete_todo", {"todo_id": tid})
        if ok:
            counts["deleted"] += 1
        else:
            note_error(f"delete #{tid}", res)

    # ── standalone recurrence ─────────────────────────────────────────────
    for item in batch.get("set_recurrence") or []:
        if not isinstance(item, dict):
            continue
        ok, res = _run(db, user_id, "set_recurrence", item)
        if ok:
            counts["recurring"] += 1
        else:
            note_error(f"recurrence #{item.get('todo_id', '?')}", res)

    # ── tags ──────────────────────────────────────────────────────────────
    for item in batch.get("add_tag") or []:
        if not isinstance(item, dict):
            continue
        ok, res = _run(db, user_id, "add_tag_to_todo", item)
        if ok:
            counts["tagged"] += 1
        else:
            note_error(f"tag #{item.get('todo_id', '?')}", res)

    # ── user context (memory) ─────────────────────────────────────────────
    for item in batch.get("save_context") or []:
        if not isinstance(item, dict):
            continue
        ok, res = _run(db, user_id, "save_user_context", item)
        if ok:
            counts["context"] += 1
        else:
            note_error(f"note '{item.get('tag', '?')}'", res)

    for tag in batch.get("delete_context") or []:
        ok, res = _run(db, user_id, "delete_user_context", {"tag": tag})
        if ok:
            counts["context"] += 1
        else:
            note_error(f"delete note '{tag}'", res)

    return {"counts": counts, "errors": errors}


def summarize_counts(counts: dict, errors: list[str]) -> str:
    """Turn accumulated counts + errors into a friendly one-liner (+ error list)."""
    labels = [
        ("created", "task", "tasks", "created"),
        ("updated", "task", "tasks", "updated"),
        ("completed", "task", "tasks", "completed"),
        ("deleted", "task", "tasks", "deleted"),
        ("recurring", "task", "tasks", "set to repeat"),
        ("subtasks", "subtask", "subtasks", "added"),
        ("tagged", "tag", "tags", "applied"),
        ("context", "note", "notes", "saved to memory"),
    ]
    parts = []
    for key, sing, plur, verb in labels:
        n = counts.get(key, 0)
        if n:
            parts.append(f"{n} {sing if n == 1 else plur} {verb}")

    if parts:
        summary = "Done — " + ", ".join(parts) + "."
    elif errors:
        summary = "I couldn't apply those changes."
    else:
        summary = "Nothing needed changing."

    if errors:
        shown = errors[:5]
        summary += f"\n\n⚠️ {len(errors)} couldn't be applied:\n" + "\n".join(
            f"• {e}" for e in shown
        )
        if len(errors) > 5:
            summary += f"\n• …and {len(errors) - 5} more."

    return summary
