"""Agent orchestrator — builds the RAG context and runs the assistant."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from core.config import IST
from agent.llm import get_client
from agent.context import build_user_context
from agent.db_ops import get_or_create_session, get_recent_messages, store_message
from agent.assistant import run_assistant
from agent.ws_manager import manager
from apps.auth.models import User

logger = logging.getLogger(__name__)


async def run_agent_async(db: Session, user_id: int, user_message: str):
    """Main entry point — retrieve the user's data, then run the assistant."""
    client, model, _light_model = get_client()

    session = get_or_create_session(db, user_id)
    store_message(db, session.id, "user", user_message)

    user = db.query(User).filter(User.id == user_id).first()
    current_time_str = datetime.now(IST).strftime("%Y-%m-%d %I:%M %p %Z")

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
        model_name=model,
    )

    session.updated_at = datetime.now(IST)
    db.commit()

    await manager.send_personal_message({
        "type": "usage",
        "agents": [f"assistant ({model})"],
        "tokens": result.get("usage", {}),
    }, user_id)
