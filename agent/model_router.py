"""Cheap pre-flight router that picks the light or heavy model for a turn."""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from agent.prompts import ROUTER_PROMPT

logger = logging.getLogger(__name__)


async def choose_model(
    client: AsyncOpenAI,
    user_message: str,
    light_model: str,
    heavy_model: str,
) -> tuple[str, dict]:
    """Classify the turn on the cheapest model and return (model_name, usage).

    A single, tiny, non-streaming call on the light model decides whether the
    turn needs the heavy model. Fails open to the light model — a routing
    hiccup must never block the turn, and the cheaper model is the safe default.
    The returned usage is folded into the turn's totals by the caller so the
    router's handful of tokens are still metered.
    """
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    try:
        resp = await client.chat.completions.create(
            model=light_model,
            messages=[
                {"role": "system", "content": ROUTER_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
            max_tokens=4,
        )
    except Exception as e:  # noqa: BLE001 — routing must not sink the turn
        logger.warning("Model router failed, defaulting to light model: %s", e)
        return light_model, usage

    if resp.usage:
        usage["prompt_tokens"] = resp.usage.prompt_tokens or 0
        usage["completion_tokens"] = resp.usage.completion_tokens or 0
        usage["total_tokens"] = resp.usage.total_tokens or (
            usage["prompt_tokens"] + usage["completion_tokens"]
        )

    choice = (resp.choices[0].message.content or "").strip().upper()
    model_name = heavy_model if choice.startswith("H") else light_model
    logger.info("Router chose %s (raw=%r)", model_name, choice)
    return model_name, usage
