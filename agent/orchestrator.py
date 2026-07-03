"""Agent orchestrator — classifies user intent and routes to the right agent."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from core.config import settings, IST
from agent.db_ops import get_or_create_session, get_recent_messages, store_message
from agent.models import ChatMessage
from agent.simple_agent import run_simple_agent
from agent.complex_agent import run_complex_agent
from agent.ws_manager import manager
from agent.prompts import CLASSIFIER_PROMPT
from apps.auth.models import User

logger = logging.getLogger(__name__)


async def run_agent_async(db: Session, user_id: int, user_message: str):
    """Main entry point — classify → route to greeting / simple / complex agent."""
    if settings.AI_PROVIDER == "groq":
        client = AsyncOpenAI(
            api_key=settings.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )
        model = settings.GROQ_MODEL
        light_model = settings.GROQ_LIGHT_MODEL
    else:
        client = AsyncOpenAI(
            api_key=settings.GEMINI_API_KEY,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        model = settings.GEMINI_MODEL
        light_model = settings.GEMINI_LIGHT_MODEL

    session = get_or_create_session(db, user_id)
    store_message(db, session.id, "user", user_message)

    user = db.query(User).filter(User.id == user_id).first()
    current_time_str = datetime.now(IST).strftime("%Y-%m-%d %I:%M %p %Z")

    agents_used: list[str] = []
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def _add_usage(u: dict) -> None:
        total_usage["prompt_tokens"] += u.get("prompt_tokens", 0)
        total_usage["completion_tokens"] += u.get("completion_tokens", 0)
        total_usage["total_tokens"] += u.get("total_tokens", 0)

    # ── 0. CONTINUATION CHECK ────────────────────────────────────────────
    # If the last tool message was ask_user_question, the user is replying
    # to a question — skip classification and go straight to the complex agent.
    if _is_continuation(db, session.id):
        agents_used.append("continuation (skipped classifier)")
        await manager.send_personal_message({"type": "status", "message": "Resuming..."}, user_id)

        history = get_recent_messages(db, session.id)
        result = await run_complex_agent(
            client=client, db=db, user_id=user_id, session_id=session.id,
            history=history, role="general", current_time_str=current_time_str,
            user_prefs=user.preferences if user else None,
            model_name=model,
        )
        agents_used.append(f"complex_agent ({model})")
        _add_usage(result.get("usage", {}))
        session.updated_at = datetime.now(IST)
        db.commit()
        await _send_usage(user_id, agents_used, total_usage)
        return

    # ── 1. CLASSIFY ──────────────────────────────────────────────────────
    await manager.send_personal_message({"type": "status", "message": "Analyzing..."}, user_id)

    classification = await _classify(client, user_message, current_time_str, light_model)
    agents_used.append(f"classifier ({light_model})")
    _add_usage(classification.get("usage", {}))

    mode = classification.get("mode", "simple")
    role = classification.get("role", "general")

    # ── 2A. GREETING ─────────────────────────────────────────────────────
    if mode == "greeting":
        response_text = classification.get("response", "Hey! How can I help you?")
        msg_obj = store_message(db, session.id, "assistant", response_text)
        await manager.send_personal_message({
            "type": "message",
            "message": {"id": msg_obj.id, "role": "assistant", "content": response_text, "created_at": msg_obj.created_at.isoformat()},
        }, user_id)
        session.updated_at = datetime.now(IST)
        db.commit()
        await _send_usage(user_id, agents_used, total_usage)
        return

    # ── 2B. SIMPLE TASK ──────────────────────────────────────────────────
    history = get_recent_messages(db, session.id)

    if mode == "simple":
        print("RAN SIMPLE AGENT")
        await manager.send_personal_message({"type": "status", "message": "Working..."}, user_id)
        result = await run_simple_agent(
            client=client, db=db, user_id=user_id, session_id=session.id,
            history=history, role=role, current_time_str=current_time_str,
            user_prefs=user.preferences if user else None,
            model_name=light_model,
        )
        agents_used.append(f"simple_agent ({light_model})")
        _add_usage(result.get("usage", {}))
        session.updated_at = datetime.now(IST)
        db.commit()
        await _send_usage(user_id, agents_used, total_usage)
        return

    # ── 2C. COMPLEX TASK ─────────────────────────────────────────────────
    await manager.send_personal_message({"type": "status", "message": "Planning workflow..."}, user_id)
    result = await run_complex_agent(
        client=client, db=db, user_id=user_id, session_id=session.id,
        history=history, role=role, current_time_str=current_time_str,
        user_prefs=user.preferences if user else None,
        model_name=model,
    )
    agents_used.append(f"complex_agent ({model})")
    _add_usage(result.get("usage", {}))
    session.updated_at = datetime.now(IST)
    db.commit()
    await _send_usage(user_id, agents_used, total_usage)


# ─────────────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────────────

def _is_continuation(db: Session, session_id: int) -> bool:
    """Check if the previous message (before the current user message) was ask_user_question."""
    last_msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(2)
        .all()
    )
    if len(last_msgs) < 2:
        return False
        
    prev_msg = last_msgs[1]  # index 0 is the newly inserted user message
    if prev_msg.role == "tool" and prev_msg.tool_calls:
        if prev_msg.tool_calls.get("name") == "ask_user_question":
            return True
    
    # Also support Groq/Llama models hallucinating the tool call in the text stream
    if prev_msg.role == "assistant" and prev_msg.content:
        if "<function=ask_user_question>" in prev_msg.content:
            return True
            
    return False


async def _classify(client: AsyncOpenAI, user_message: str, current_time_str: str, light_model: str) -> dict:
    """Run the light model classifier to decide greeting / simple / complex + role."""
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    try:
        response = await client.chat.completions.create(
            model=light_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": CLASSIFIER_PROMPT.format(current_date=current_time_str)},
                {"role": "user", "content": user_message},
            ],
        )
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens or 0,
                "completion_tokens": response.usage.completion_tokens or 0,
                "total_tokens": response.usage.total_tokens or 0,
            }
        raw = response.choices[0].message.content.strip()
        # Find the first '{' and last '}' to extract just the JSON
        start_idx = raw.find('{')
        end_idx = raw.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            raw = raw[start_idx:end_idx + 1]
        data = json.loads(raw)
        data["usage"] = usage
        return data
    except Exception as e:
        logger.error("Classifier failed: %s", e)
        return {"mode": "simple", "role": "general", "response": None, "task_summary": user_message, "usage": usage}


async def _send_usage(user_id: int, agents: list[str], usage: dict) -> None:
    await manager.send_personal_message({"type": "usage", "agents": agents, "tokens": usage}, user_id)
