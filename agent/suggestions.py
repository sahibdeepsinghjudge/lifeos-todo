"""AI subtask suggestions — light model proposes subtasks for a single task."""

from __future__ import annotations

import json
import logging

from agent.llm import get_client
from agent.prompts import SUBTASK_SUGGESTION_PROMPT
from apps.todo.models import Todo

logger = logging.getLogger(__name__)

MAX_SUGGESTIONS = 5


async def suggest_subtasks(todo: Todo) -> list[str]:
    """Return up to 5 suggested subtask titles for the given todo.

    Returns an empty list on any model/parsing failure so the endpoint
    degrades gracefully instead of erroring the task-details screen.
    """
    client, _model, light_model = get_client()

    existing_titles = [
        s.title for s in (todo.subtasks or []) if s.deleted_at is None
    ]

    prompt = SUBTASK_SUGGESTION_PROMPT.format(
        title=todo.title,
        description=todo.description or "(none)",
        existing=json.dumps(existing_titles) if existing_titles else "(none)",
    )

    try:
        response = await client.chat.completions.create(
            model=light_model,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        start_idx = raw.find("{")
        end_idx = raw.rfind("}")
        if start_idx != -1 and end_idx > start_idx:
            raw = raw[start_idx:end_idx + 1]
        data = json.loads(raw)
        suggestions = data.get("suggestions", [])
        if not isinstance(suggestions, list):
            return []

        existing_lower = {t.strip().lower() for t in existing_titles}
        cleaned: list[str] = []
        for s in suggestions:
            if not isinstance(s, str):
                continue
            title = s.strip()
            if title and title.lower() not in existing_lower:
                cleaned.append(title)
        return cleaned[:MAX_SUGGESTIONS]
    except Exception as e:
        logger.error("Subtask suggestion failed for todo %s: %s", todo.id, e)
        return []
