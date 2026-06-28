from __future__ import annotations

import json
from datetime import datetime, timezone

from openai import OpenAI
from sqlalchemy.orm import Session

from core.config import settings
from agent.models import ChatSession, ChatMessage
from agent.tools import TOOLS
from agent.handlers import handle_tool_call
from agent.prompts import ROUTER_PROMPT, BASE_RULES, ROLE_PROMPTS

def classify_intent(client: OpenAI, user_message: str) -> str:
    """Classify the user's intent to select the best specialized role."""
    messages = [
        {"role": "system", "content": ROUTER_PROMPT},
        {"role": "user", "content": user_message}
    ]
    
    try:
        response = client.chat.completions.create(
            model=settings.GEMINI_MODEL,
            messages=messages,
            temperature=0.0,
        )
        role = response.choices[0].message.content.strip().lower()
        if role not in ROLE_PROMPTS:
            return "general"
        return role
    except Exception as e:
        print(f"Classification failed: {e}")
        return "general"

def get_or_create_session(db: Session, user_id: int) -> ChatSession:
    """Get the most recent session or create a new one."""
    session = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc())
        .first()
    )
    if not session:
        session = ChatSession(user_id=user_id)
        db.add(session)
        db.commit()
        db.refresh(session)
    return session


def get_recent_messages(db: Session, session_id: int, limit: int = 40) -> list[dict]:
    """Load last N messages formatted for OpenAI API."""
    messages_db = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    messages_db.reverse()  # Chronological order
    
    # Ensure the history starts with a user message to prevent sequence validation errors from Gemini
    while messages_db and messages_db[0].role != "user":
        messages_db.pop(0)

    openai_messages: list[dict] = []
    for msg in messages_db:
        if msg.role == "tool":
            # Tool result messages
            openai_messages.append({
                "role": "tool",
                "content": msg.content or "",
                "tool_call_id": msg.tool_calls.get("tool_call_id", "") if msg.tool_calls else "",
                "name": msg.tool_calls.get("name", "") if msg.tool_calls else "",
            })
        elif msg.role == "assistant" and msg.tool_calls:
            # Assistant message with tool calls
            openai_messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": msg.tool_calls.get("calls", []) if msg.tool_calls else [],
            })
        else:
            openai_messages.append({
                "role": msg.role,
                "content": msg.content or "",
            })
    return openai_messages


def store_message(
    db: Session,
    session_id: int,
    role: str,
    content: str | None,
    tool_calls: dict | None = None,
) -> ChatMessage:
    """Store a message in the database."""
    msg = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        tool_calls=tool_calls,
    )
    db.add(msg)
    db.commit()
    return msg


def run_agent(db: Session, user_id: int, user_message: str) -> dict:
    """Main agentic loop.

    1. Load conversation history
    2. Append user message
    3. Call Gemini API with tools
    4. If tool_calls → execute → loop
    5. Return final response
    """
    client = OpenAI(
        api_key=settings.GEMINI_API_KEY,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )

    session = get_or_create_session(db, user_id)

    # Store user message
    store_message(db, session.id, "user", user_message)

    # Classify intent to select the best role
    selected_role = classify_intent(client, user_message)
    role_prompt = ROLE_PROMPTS.get(selected_role, ROLE_PROMPTS["general"])
    dynamic_system_prompt = f"{role_prompt}\n\n{BASE_RULES}"

    # Build message history
    history = get_recent_messages(db, session.id)
    messages: list[dict] = [{"role": "system", "content": dynamic_system_prompt}] + history

    actions_taken: list[dict] = []
    max_iterations = 10  # Safety limit

    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=settings.GEMINI_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )

        choice = response.choices[0]
        assistant_message = choice.message

        if assistant_message.tool_calls:
            # Store assistant message with tool calls
            tool_calls_data = {
                "calls": [tc.model_dump(exclude_unset=True) for tc in assistant_message.tool_calls]
            }
            store_message(db, session.id, "assistant", assistant_message.content, tool_calls_data)

            # Add assistant message to conversation
            messages.append({
                "role": "assistant",
                "content": assistant_message.content,
                "tool_calls": tool_calls_data["calls"],
            })

            # Execute each tool call
            for tc in assistant_message.tool_calls:
                tool_name = tc.function.name
                try:
                    arguments = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}

                try:
                    result = handle_tool_call(tool_name, arguments, db, user_id)
                    actions_taken.append({"tool": tool_name, "result": json.loads(result)})
                except Exception as e:
                    result = json.dumps({"error": str(e)})
                    actions_taken.append({"tool": tool_name, "error": str(e)})

                # Store tool result
                store_message(db, session.id, "tool", result, {"tool_call_id": tc.id, "name": tc.function.name})

                # Add to messages
                messages.append({
                    "role": "tool",
                    "content": result,
                    "tool_call_id": tc.id,
                    "name": tc.function.name,
                })
        else:
            # No tool calls — we have the final response
            final_text = assistant_message.content or ""
            store_message(db, session.id, "assistant", final_text)

            # Update session timestamp
            session.updated_at = datetime.now(timezone.utc)
            db.commit()

            return {
                "response": final_text,
                "actions": actions_taken,
            }

    # Safety: if we hit max iterations
    fallback = "I've completed several actions but reached my processing limit. Here's what I did so far."
    store_message(db, session.id, "assistant", fallback)
    return {"response": fallback, "actions": actions_taken}
