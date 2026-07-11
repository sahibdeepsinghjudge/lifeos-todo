"""The OttoAI assistant — a single RAG-grounded agent for day planning.

Answers from the user-data snapshot injected into its system prompt and
performs simple single actions (create/edit/complete todos, reminders, tags)
via tools. Multi-step workflows are intentionally out of scope.
"""

from __future__ import annotations

import logging

from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from agent.prompts import ASSISTANT_PROMPT
from agent.loop_utils import (
    call_model_stream,
    handle_tool_calls,
    send_final,
    is_terminal_response,
    execute_terminal_and_summarize,
)

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5


async def run_assistant(
    client: AsyncOpenAI,
    db: Session,
    user_id: int,
    session_id: int,
    history: list[dict],
    current_time_str: str,
    user_context: str,
    model_name: str,
) -> dict:
    """Run the assistant loop until it produces a final text reply.

    Returns:
        {"text": str | None, "usage": dict}
    """
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    system_prompt = ASSISTANT_PROMPT.format(
        current_date=current_time_str,
        user_context=user_context,
    )

    messages: list[dict] = [{"role": "system", "content": system_prompt}] + history

    tool_rounds = 0
    recent_calls: list[tuple[str, str]] = []

    while True:
        if tool_rounds >= MAX_TOOL_ROUNDS:
            fallback = "I've done what I can for this request — let me know if you'd like anything adjusted."
            await send_final(db, session_id, user_id, fallback)
            return {"text": fallback, "usage": usage}

        tool_rounds += 1

        response = await call_model_stream(
            client=client,
            model=model_name,
            messages=messages,
            usage=usage,
            db=db,
            session_id=session_id,
            user_id=user_id,
        )

        if response.final_text is not None:
            return {"text": response.final_text, "usage": usage}

        messages.append(response.assistant_message)

        # Fast path: the model asked only for terminal writes (the common
        # "create these / update those" case, ideally one apply_todo_changes
        # call). Execute them and summarize in Python — no second LLM round.
        if is_terminal_response(response.tool_calls):
            summary = await execute_terminal_and_summarize(
                tool_calls=response.tool_calls,
                db=db,
                user_id=user_id,
                session_id=session_id,
            )
            await send_final(db, session_id, user_id, summary)
            return {"text": summary, "usage": usage}

        # Otherwise (reads the model must see, or a clarifying question):
        # execute and loop back so it can react to the results.
        should_stop = await handle_tool_calls(
            response=response,
            messages=messages,
            db=db,
            user_id=user_id,
            session_id=session_id,
            recent_calls=recent_calls,
        )

        if should_stop:
            return {"text": "Hmmm... got into some loop, try again", "usage": usage}
