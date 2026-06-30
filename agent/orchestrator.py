from __future__ import annotations

import json
from datetime import datetime
import asyncio

from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from core.config import settings, IST
from agent.models import ChatSession, ChatMessage
from agent.tools import TOOLS
from agent.handlers import handle_tool_call
from agent.prompts import ROUTER_PROMPT, BASE_RULES, ROLE_PROMPTS, LIGHT_MODEL_PROMPT
from agent.ws_manager import manager
from apps.auth.models import User

async def classify_intent(client: AsyncOpenAI, user_message: str) -> str:
    """Classify the user's intent to select the best specialized role."""
    messages = [
        {"role": "system", "content": ROUTER_PROMPT},
        {"role": "user", "content": user_message}
    ]
    
    try:
        response = await client.chat.completions.create(
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
            # Tool result messages formatted as user context
            tool_name = msg.tool_calls.get("name", "tool") if msg.tool_calls else "tool"
            openai_messages.append({
                "role": "user",
                "content": f"[Tool Result for {tool_name}]: {msg.content or ''}",
            })
        elif msg.role == "assistant" and msg.tool_calls:
            # Assistant message with tool calls flattened
            content = msg.content or ""
            try:
                calls = msg.tool_calls.get("calls", [])
                func_names = [c.get("function", {}).get("name", "unknown") for c in calls if isinstance(c, dict)]
                if func_names:
                    content += f"\n[Called tools: {', '.join(func_names)}]"
            except Exception:
                pass
            
            openai_messages.append({
                "role": "assistant",
                "content": content.strip() or "Processed tool.",
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


async def run_agent_async(db: Session, user_id: int, user_message: str):
    """Main agentic loop with WebSockets and 2-tier model architecture."""
    client = AsyncOpenAI(
        api_key=settings.GEMINI_API_KEY,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )

    session = get_or_create_session(db, user_id)
    store_message(db, session.id, "user", user_message)

    user = db.query(User).filter(User.id == user_id).first()

    # --- 1. LIGHT MODEL PASS (Context Extraction & Prompt Refinement) ---
    await manager.send_personal_message({"type": "status", "message": "Extracting context..."}, user_id)

    current_time_str = datetime.now(IST).strftime("%Y-%m-%d %I:%M %p %Z")

    try:
        light_response = await client.chat.completions.create(
            model=settings.GEMINI_LIGHT_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": LIGHT_MODEL_PROMPT.format(current_date=current_time_str)},
                {"role": "user", "content": f"User's current preferences: {user.preferences if user else ''}\n\nUser Message: {user_message}"}
            ]
        )
        light_data = json.loads(light_response.choices[0].message.content)
        extracted_context = light_data.get("extracted_context", [])
        refined_prompt = light_data.get("refined_prompt", user_message)

        if extracted_context and user:
            # Auto-save new context
            new_prefs_str = json.dumps(extracted_context)
            if user.preferences:
                user.preferences += "\n" + new_prefs_str
            else:
                user.preferences = new_prefs_str
            db.commit()

    except Exception as e:
        print(f"Light model parsing failed: {e}")
        refined_prompt = user_message

    # --- 2. ADVANCED MODEL PASS ---
    await manager.send_personal_message({"type": "status", "message": "Thinking..."}, user_id)

    selected_role = await classify_intent(client, refined_prompt)
    role_prompt = ROLE_PROMPTS.get(selected_role, ROLE_PROMPTS["general"])
    
    dynamic_system_prompt = f"{role_prompt}\n\n{BASE_RULES.format(current_date=current_time_str)}\n\nIMPORTANT: You must ask questions if you are unsure or need clarification before doing destructive actions."
    
    if user and user.preferences:
        dynamic_system_prompt += f"\n\n### User Personal Context:\n{user.preferences}\n"

    history = get_recent_messages(db, session.id)
    
    # Replace the user's raw message with the refined prompt for the advanced model's context
    if history and history[-1]["role"] == "user":
        history[-1]["content"] = f"Refined Intent: {refined_prompt}"

    messages: list[dict] = [{"role": "system", "content": dynamic_system_prompt}] + history
    max_iterations = 10

    for _ in range(max_iterations):
        stream = await client.chat.completions.create(
            model=settings.GEMINI_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            stream=True
        )

        tool_calls_buffer = {}
        content_buffer = ""
        is_tool_call = False

        msg_id_sent = False
        msg_id = None
        
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            
            if delta.tool_calls:
                is_tool_call = True
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name or "", "arguments": ""}
                        }
                    if tc.function.arguments:
                        tool_calls_buffer[idx]["function"]["arguments"] += tc.function.arguments
            elif delta.content:
                content_buffer += delta.content
                if not msg_id_sent:
                    # Save a placeholder message to get an ID for streaming
                    msg_obj = store_message(db, session.id, "assistant", "")
                    msg_id = msg_obj.id
                    msg_id_sent = True
                    
                    # Send initial message format to UI
                    await manager.send_personal_message({
                        "type": "message",
                        "message": {
                            "id": msg_id,
                            "role": "assistant",
                            "content": "",
                            "created_at": msg_obj.created_at.isoformat()
                        }
                    }, user_id)
                
                # Stream chunk to UI
                await manager.send_personal_message({
                    "type": "message_chunk",
                    "id": msg_id,
                    "content": delta.content
                }, user_id)

        if is_tool_call:
            # Reconstruct tool calls
            assembled_tool_calls = list(tool_calls_buffer.values())
            
            tool_calls_data = {
                "calls": assembled_tool_calls
            }
            store_message(db, session.id, "assistant", content_buffer, tool_calls_data)

            # Flatten tool call for next loop iteration
            func_names = [tc.get("function", {}).get("name", "unknown") for tc in assembled_tool_calls]
            flattened_content = content_buffer or ""
            if func_names:
                flattened_content += f"\n[Called tools: {', '.join(func_names)}]"

            messages.append({
                "role": "assistant",
                "content": flattened_content.strip() or "Processed tool.",
            })

            should_break = False
            for tc in assembled_tool_calls:
                tool_name = tc["function"]["name"]
                
                try:
                    arguments = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    arguments = {}

                if tool_name == "ask_user_question":
                    questions = arguments.get("questions", [])
                    if isinstance(questions, str):
                        questions = [questions]
                    for q in questions:
                        await manager.send_personal_message({"type": "question", "question": q}, user_id)
                    should_break = True
                else:
                    await manager.send_personal_message({"type": "status", "message": f"Running {tool_name}..."}, user_id)

                try:
                    result = await asyncio.to_thread(handle_tool_call, tool_name, arguments, db, user_id)
                except Exception as e:
                    result = json.dumps({"error": str(e)})

                store_message(db, session.id, "tool", result, {"tool_call_id": tc["id"], "name": tool_name})

                # Flatten tool result as user message
                messages.append({
                    "role": "user",
                    "content": f"[Tool Result for {tool_name}]: {result or ''}",
                })
            
            if should_break:
                return
        else:
            final_text = content_buffer
            if not msg_id_sent:
                # If content was streamed too fast or empty, create final message
                msg_obj = store_message(db, session.id, "assistant", final_text)
                await manager.send_personal_message({
                    "type": "message",
                    "message": {
                        "id": msg_obj.id,
                        "role": "assistant",
                        "content": final_text,
                        "created_at": msg_obj.created_at.isoformat()
                    }
                }, user_id)
            else:
                # Update the stored placeholder message with final content
                msg_obj = db.query(ChatMessage).filter(ChatMessage.id == msg_id).first()
                if msg_obj:
                    msg_obj.content = final_text
                    db.commit()

            session.updated_at = datetime.now(IST)
            db.commit()
            return

    fallback = "I've reached my processing limit. Here's what I did so far."
    msg_obj = store_message(db, session.id, "assistant", fallback)
    await manager.send_personal_message({
        "type": "message",
        "message": {
            "id": msg_obj.id,
            "role": "assistant",
            "content": fallback,
            "created_at": msg_obj.created_at.isoformat()
        }
    }, user_id)
