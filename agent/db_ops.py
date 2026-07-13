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


def get_history_for_prompt(db: Session, session: ChatSession) -> list[dict]:
    """The prompt tail: recent messages NOT yet folded into the session's
    rolling summary, formatted for the OpenAI API.

    Everything older lives in `session.summary` (injected into the system
    prompt), so a turn carries "summary + short tail" instead of the whole
    chat — the tail cap also bounds legacy sessions until the summarizer
    catches up at end of turn.
    """
    from agent.summarizer import KEEP_RECENT

    since = session.summary_upto_message_id or 0
    messages_db = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id, ChatMessage.id > since)
        .order_by(ChatMessage.id.desc())
        .limit(KEEP_RECENT)
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
            tool_name = msg.tool_calls.get("name", "") if msg.tool_calls else ""
            # Gemini requires non-empty name on every function_response;
            # skip malformed tool results that would cause a 400.
            if not tool_name or not tool_call_id:
                continue
            openai_messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": msg.content or "",
            })
        elif msg.role == "assistant" and msg.tool_calls:
            calls = msg.tool_calls.get("calls", [])
            # Reconstruct the tool_calls list as expected by OpenAI SDK.
            # Filter out entries with missing function names (Gemini rejects them).
            native_calls = []
            for c in calls:
                if isinstance(c, dict):
                    func = c.get("function", {})
                    if not func.get("name"):
                        continue
                    native_calls.append({
                        "id": c.get("id"),
                        "type": "function",
                        "function": func,
                    })
            
            assistant_msg: dict = {
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

    # Final pass: ensure every assistant message that declares tool_calls has
    # a matching tool-result message immediately after it. Gemini rejects
    # dangling tool_calls without corresponding function_response entries.
    cleaned: list[dict] = []
    i = 0
    while i < len(openai_messages):
        m = openai_messages[i]
        if m.get("tool_calls"):
            expected_ids = {tc["id"] for tc in m["tool_calls"] if tc.get("id")}
            # Collect the tool results that follow
            j = i + 1
            following_tool_ids: set[str] = set()
            while j < len(openai_messages) and openai_messages[j]["role"] == "tool":
                following_tool_ids.add(openai_messages[j].get("tool_call_id", ""))
                j += 1
            # Only keep if every tool_call has a matching result
            if expected_ids and expected_ids.issubset(following_tool_ids):
                cleaned.append(m)
            else:
                # Drop the assistant message and its orphaned tool results
                i = j
                continue
        else:
            cleaned.append(m)
        i += 1

    return cleaned


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
