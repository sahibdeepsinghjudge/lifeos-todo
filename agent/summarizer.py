"""Rolling conversation summary — keeps the per-turn prompt small.

Instead of replaying dozens of raw messages (tool payloads included) every
turn, each session carries a compact summary of everything older than the
recent tail. The fold runs on the cheap light model at the END of a turn —
after the reply has already been sent — so it adds zero perceived latency and
roughly one small call per dozen messages.
"""

from __future__ import annotations

import logging

from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from agent.models import ChatSession, ChatMessage
from agent.prompts import SUMMARIZE_PROMPT

logger = logging.getLogger(__name__)

# Raw messages kept verbatim in the prompt tail. Everything older gets folded
# into the summary. Must match db_ops.get_history_for_prompt's tail size so
# the summary and the tail meet exactly, with no gap and no overlap.
KEEP_RECENT = 12

# Don't bother summarizing until at least this many messages sit beyond the
# tail — folding two lines at a time would waste calls.
MIN_FOLD = 8

# Cap messages folded in one call; a huge pre-existing backlog catches up over
# a few turns instead of building one giant request.
MAX_FOLD = 60


def _transcript(messages: list[ChatMessage]) -> str:
    """Plain-text transcript of the foldable content. Tool rows and empty
    tool-call shells are skipped — the outcome is already reflected in the
    assistant's visible replies."""
    lines: list[str] = []
    for m in messages:
        if m.role not in ("user", "assistant"):
            continue
        text = (m.content or "").strip()
        if not text:
            continue
        speaker = "User" if m.role == "user" else "Assistant"
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


async def maybe_summarize(
    db: Session,
    session: ChatSession,
    client: AsyncOpenAI,
    model: str,
) -> dict:
    """Fold old messages into the session summary when the backlog is big
    enough. Returns the LLM usage dict (zeros when nothing ran). Never raises —
    a failed fold just means the next turn tries again.
    """
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    since = session.summary_upto_message_id or 0
    backlog = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id, ChatMessage.id > since)
        .order_by(ChatMessage.id.asc())
        .all()
    )
    if len(backlog) < KEEP_RECENT + MIN_FOLD:
        return usage

    fold = backlog[:-KEEP_RECENT][:MAX_FOLD]
    new_upto = fold[-1].id
    chunk = _transcript(fold)

    if not chunk:
        # Nothing meaningful in this slice (pure tool noise) — just advance the
        # pointer so the backlog can't grow unboundedly.
        session.summary_upto_message_id = new_upto
        db.commit()
        return usage

    old_summary = session.summary or "(none)"
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SUMMARIZE_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"EXISTING SUMMARY:\n{old_summary}\n\n"
                        f"NEW MESSAGES:\n{chunk}"
                    ),
                },
            ],
            temperature=0,
            max_tokens=400,
        )
    except Exception as e:  # noqa: BLE001 — summarizing must never sink a turn
        logger.warning("Chat summarization failed (will retry next turn): %s", e)
        return usage

    text = (resp.choices[0].message.content or "").strip()
    if not text:
        return usage

    if resp.usage:
        usage["prompt_tokens"] = resp.usage.prompt_tokens or 0
        usage["completion_tokens"] = resp.usage.completion_tokens or 0
        usage["total_tokens"] = resp.usage.total_tokens or (
            usage["prompt_tokens"] + usage["completion_tokens"]
        )

    session.summary = text
    session.summary_upto_message_id = new_upto
    db.commit()
    logger.info(
        "Session %s: folded %d messages into summary (upto id %d)",
        session.id, len(fold), new_upto,
    )
    return usage
