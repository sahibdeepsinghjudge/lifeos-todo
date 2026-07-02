"""Simple agent — handles independent single-action tasks using the light model."""

from __future__ import annotations

import logging

from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from agent.prompts import SIMPLE_AGENT_PROMPT, ROLE_PROMPTS
from agent.loop_utils import call_model_stream, handle_tool_calls, send_final

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 4


async def run_simple_agent(
    client: AsyncOpenAI,
    db: Session,
    user_id: int,
    session_id: int,
    history: list[dict],
    role: str,
    current_time_str: str,
    user_prefs: str | None,
    model_name: str,
) -> dict:
    """Run the light model with tools for a single independent task.

    Returns:
        {"text": str | None, "usage": dict}
    """
    if role not in ROLE_PROMPTS:
        role = "general"

    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    system_prompt = (
        f"{SIMPLE_AGENT_PROMPT.format(current_date=current_time_str)}\n\n"
        f"Role: {ROLE_PROMPTS[role]}"
    )

    if user_prefs:
        system_prompt += f"\n\nUser context:\n{user_prefs}"

    messages: list[dict] = [{"role": "system", "content": system_prompt}] + history

    tool_rounds = 0
    recent_calls: list[tuple[str, str]] = []

    while True:
        if tool_rounds >= MAX_TOOL_ROUNDS:
            fallback = "I've reached my interaction limit for this task."
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

        should_stop = await handle_tool_calls(
            response=response,
            messages=messages,
            db=db,
            user_id=user_id,
            session_id=session_id,
            recent_calls=recent_calls,
        )

        if should_stop:
            return {"text": None, "usage": usage}
