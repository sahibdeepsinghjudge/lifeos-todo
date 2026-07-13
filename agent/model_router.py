"""Cheap pre-flight router that picks the light or heavy model for a turn."""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from agent.prompts import ROUTER_PROMPT

logger = logging.getLogger(__name__)

from core.config import settings
    
if settings.AI_PROVIDER == "groq":
    heavy_model = settings.GROQ_MODEL
    light_model = settings.GROQ_LIGHT_MODEL
else:
    heavy_model = settings.GEMINI_MODEL
    light_model = settings.GEMINI_LIGHT_MODEL

class ContextNeeds:
    """Which parts of the user's data this turn needs in the prompt."""

    def __init__(self, todos: bool, prefs: bool):
        self.todos = todos
        self.prefs = prefs

    @classmethod
    def everything(cls) -> "ContextNeeds":
        """The fail-open default — matches the old always-load behaviour."""
        return cls(todos=True, prefs=True)


async def choose_model(
    client: AsyncOpenAI,
    user_message: str,
) -> tuple[str, "ContextNeeds", dict]:
    """Classify the turn on the cheapest model.

    Returns (model_name, context_needs, usage). One tiny, non-streaming call
    decides both which model runs the turn AND which user data to load into
    the prompt — fragmenting the context costs zero extra requests.

    Fails open to (light model, full context) — a routing hiccup must never
    block the turn or starve it of data; token saving is best-effort.
    """
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    try:
        resp = await client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": ROUTER_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
            max_tokens=6,
        )
    except Exception as e:  # noqa: BLE001 — routing must not sink the turn
        logger.warning("Model router failed, defaulting to light+full: %s", e)
        return light_model, ContextNeeds.everything(), usage
    # NOT UPDATING THE USAGE FOR THE ROUTER
    # if resp.usage:
    #     usage["prompt_tokens"] = resp.usage.prompt_tokens or 0
    #     usage["completion_tokens"] = resp.usage.completion_tokens or 0
    #     usage["total_tokens"] = resp.usage.total_tokens or (
    #         usage["prompt_tokens"] + usage["completion_tokens"]
    #     )

    choice = (resp.choices[0].message.content or "").strip().upper()
    model_name = heavy_model if choice.startswith("H") else light_model

    # Context letters: T tasks, P prefs, N none. An answer with no recognised
    # letters means the classifier went off-script — fail open to everything.
    if any(c in choice for c in "TPN"):
        needs = ContextNeeds(todos="T" in choice, prefs="P" in choice)
    else:
        needs = ContextNeeds.everything()

    logger.info(
        "Router chose %s, context todos=%s prefs=%s (raw=%r)",
        model_name, needs.todos, needs.prefs, choice,
    )
    return model_name, needs, usage
