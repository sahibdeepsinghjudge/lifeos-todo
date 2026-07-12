"""Agent orchestrator — builds the RAG context and runs the assistant."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from core.config import IST
from agent.llm import get_client, get_enrichment_client
from agent.model_router import choose_model
from agent.context import build_user_context
from agent.db_ops import get_or_create_session, get_recent_messages, store_message
from agent.assistant import run_assistant
from agent.ws_manager import manager
from apps.auth.models import User
from apps.usage import service as usage_service

logger = logging.getLogger(__name__)


async def run_agent_async(db: Session, user_id: int, user_message: str):
    """Main entry point — retrieve the user's data, then run the assistant."""
    client, heavy_model, light_model = get_client()
    enrichment_client = get_enrichment_client()[0]

    session = get_or_create_session(db, user_id)
    store_message(db, session.id, "user", user_message)

    user = db.query(User).filter(User.id == user_id).first()
    current_time_str = datetime.now(IST).strftime("%Y-%m-%d %I:%M %p %Z")

    # A tiny classifier on the cheapest model decides which model runs the turn:
    # light for questions/chat/small edits, heavy for complex planning.
    model_name, route_usage = await choose_model(enrichment_client, user_message)

    await manager.send_personal_message({"type": "status", "message": "Thinking..."}, user_id)

    user_context = build_user_context(
        db, user_id, user.preferences if user else None
    )
    history = get_recent_messages(db, session.id)

    result = await run_assistant(
        client=client,
        db=db,
        user_id=user_id,
        session_id=session.id,
        history=history,
        current_time_str=current_time_str,
        user_context=user_context,
        model_name=model_name,
    )

    session.updated_at = datetime.now(IST)
    db.commit()

    # Fold the router's handful of tokens into the turn's totals so metering is
    # complete, then record one row per turn (keeps the admin turn count honest).
    turn_usage = result.get("usage") or {}
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        turn_usage[k] = turn_usage.get(k, 0) + route_usage.get(k, 0)

    # Persist this turn's token usage for per-customer metering / admin.
    usage_service.record_usage(db, user_id, model_name, turn_usage)

    # Every AI interaction earns a streak point (shown in Settings).
    usage_service.record_streak(db, user_id)

    await manager.send_personal_message({
        "type": "usage",
        "agents": [f"router ({light_model})", f"assistant ({model_name})"],
        "tokens": turn_usage,
    }, user_id)
