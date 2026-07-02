"""Database helpers for the agent chat pipeline."""

from __future__ import annotations

from sqlalchemy.orm import Session

from agent.models import ChatSession, ChatMessage


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
    """Load last N messages formatted for OpenAI API (flattened, no native tool messages)."""
    messages_db = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    messages_db.reverse()  # Chronological order

    # Ensure the history starts with a user message (Gemini validation requirement)
    while messages_db and messages_db[0].role != "user":
        messages_db.pop(0)

    openai_messages: list[dict] = []
    for msg in messages_db:
        if msg.role == "tool":
            tool_call_id = msg.tool_calls.get("tool_call_id", "") if msg.tool_calls else ""
            tool_name = msg.tool_calls.get("name", "tool") if msg.tool_calls else "tool"
            openai_messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": msg.content or "",
            })
        elif msg.role == "assistant" and msg.tool_calls:
            calls = msg.tool_calls.get("calls", [])
            # Reconstruct the tool_calls list as expected by OpenAI SDK
            native_calls = []
            for c in calls:
                if isinstance(c, dict):
                    native_calls.append({
                        "id": c.get("id"),
                        "type": "function",
                        "function": c.get("function", {})
                    })
            
            assistant_msg = {
                "role": "assistant",
                "content": msg.content or None,
            }
            if native_calls:
                assistant_msg["tool_calls"] = native_calls
                
            openai_messages.append(assistant_msg)
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
