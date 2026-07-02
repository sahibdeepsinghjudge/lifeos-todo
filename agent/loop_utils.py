"""Shared utilities for agent loops and streaming."""

from __future__ import annotations

import json
import asyncio
import logging
from dataclasses import dataclass

from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from agent.tools import TOOLS
from agent.handlers import handle_tool_call
from agent.db_ops import store_message
from agent.ws_manager import manager
from agent.models import ChatMessage

logger = logging.getLogger(__name__)


@dataclass
class ToolCallBuffer:
    id: str
    name: str
    arguments: str = ""

    def append(self, chunk: str | None):
        if chunk:
            self.arguments += chunk

    @property
    def assembled(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments,
            },
        }


@dataclass
class ModelResponse:
    final_text: str | None
    assistant_message: dict
    tool_calls: list[dict]
    streamed_message_id: int | None


async def call_model_stream(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict],
    usage: dict,
    db: Session,
    session_id: int,
    user_id: int,
) -> ModelResponse:
    """Call the LLM, stream the response, and parse tool calls or final text."""
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            stream=True,
        )
    except Exception as e:
        logger.error("Agent call failed: %s", e)
        error_msg = "Something went wrong parsing the request. Please try again."
        await send_final(db, session_id, user_id, error_msg)
        return ModelResponse(final_text=error_msg, assistant_message={}, tool_calls=[], streamed_message_id=None)

    buffers: dict[int, ToolCallBuffer] = {}
    content_buf = ""
    is_tool_call = False
    msg_id_sent = False
    msg_id = None

    async for chunk in stream:
        if not chunk.choices:
            if hasattr(chunk, "usage") and chunk.usage:
                usage["prompt_tokens"] += chunk.usage.prompt_tokens or 0
                usage["completion_tokens"] += chunk.usage.completion_tokens or 0
                usage["total_tokens"] += chunk.usage.total_tokens or 0
            continue

        delta = chunk.choices[0].delta

        if delta.tool_calls:
            is_tool_call = True
            for tc in delta.tool_calls:
                buf = buffers.setdefault(
                    tc.index,
                    ToolCallBuffer(id=tc.id or "", name=tc.function.name or "")
                )
                buf.append(tc.function.arguments)
        elif delta.content:
            content_buf += delta.content
            if not msg_id_sent:
                msg_obj = store_message(db, session_id, "assistant", "")
                msg_id = msg_obj.id
                msg_id_sent = True
                await manager.send_personal_message({
                    "type": "message",
                    "message": {"id": msg_id, "role": "assistant", "content": "", "created_at": msg_obj.created_at.isoformat()},
                }, user_id)
            await manager.send_personal_message({"type": "message_chunk", "id": msg_id, "content": delta.content}, user_id)

        if hasattr(chunk, "usage") and chunk.usage:
            usage["prompt_tokens"] += chunk.usage.prompt_tokens or 0
            usage["completion_tokens"] += chunk.usage.completion_tokens or 0
            usage["total_tokens"] += chunk.usage.total_tokens or 0

    if is_tool_call:
        assembled_calls = [buf.assembled for buf in buffers.values()]
        store_message(db, session_id, "assistant", content_buf, {"calls": assembled_calls})
        assistant_msg = {
            "role": "assistant",
            "content": content_buf or None,
            "tool_calls": assembled_calls
        }
        return ModelResponse(final_text=None, assistant_message=assistant_msg, tool_calls=assembled_calls, streamed_message_id=msg_id)
    else:
        if not msg_id_sent:
            await send_final(db, session_id, user_id, content_buf)
        else:
            msg_obj = db.query(ChatMessage).filter(ChatMessage.id == msg_id).first()
            if msg_obj:
                msg_obj.content = content_buf
                db.commit()
        return ModelResponse(final_text=content_buf, assistant_message={}, tool_calls=[], streamed_message_id=msg_id)


async def handle_tool_calls(
    response: ModelResponse,
    messages: list[dict],
    db: Session,
    user_id: int,
    session_id: int,
    recent_calls: list[tuple[str, str]],
    max_repeat_tool_calls: int = 2,
) -> bool:
    """Execute tools and append results to messages. Returns True if execution should stop entirely."""
    should_stop = False
    
    for tc in response.tool_calls:
        tool_name = tc["function"]["name"]
        try:
            arguments = json.loads(tc["function"]["arguments"])
        except json.JSONDecodeError:
            arguments = {}

        # Infinite loop detection
        signature = (tool_name, tc["function"]["arguments"])
        recent_calls.append(signature)
        if recent_calls.count(signature) > max_repeat_tool_calls:
            err_msg = f"Model is repeatedly calling {tool_name} with identical arguments. Breaking loop."
            logger.error(err_msg)
            await send_final(db, session_id, user_id, "I hit a snag and am repeating myself. Let's stop here.")
            return True

        if tool_name == "ask_user_question":
            raw_qs = arguments.get("questions") or []
            if isinstance(raw_qs, str):
                raw_qs = [raw_qs]
            for q in raw_qs:
                if isinstance(q, dict):
                    q = str(q) # fallback if hallucinated a dict
                await manager.send_personal_message({"type": "question", "question": q}, user_id)
            should_stop = True
        else:
            await manager.send_personal_message({"type": "tool_start", "tool": tool_name}, user_id)

        try:
            result = await asyncio.to_thread(handle_tool_call, tool_name, arguments, db, user_id)
            if tool_name != "ask_user_question":
                await manager.send_personal_message({"type": "tool_complete", "tool": tool_name, "status": "success"}, user_id)
        except Exception as e:
            logger.error("Tool '%s' failed: %s (args=%s)", tool_name, e, arguments)
            result = json.dumps({"error": f"Tool '{tool_name}' failed: {str(e)}"})
            if tool_name != "ask_user_question":
                await manager.send_personal_message({"type": "tool_complete", "tool": tool_name, "status": "failed", "message": str(e)}, user_id)

        store_message(db, session_id, "tool", result, {"tool_call_id": tc["id"], "name": tool_name})
        messages.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "name": tool_name,
            "content": result or ""
        })

    return should_stop


async def send_final(db: Session, session_id: int, user_id: int, text: str) -> None:
    """Helper to store and send a final text message via WebSocket."""
    msg_obj = store_message(db, session_id, "assistant", text)
    await manager.send_personal_message({
        "type": "message",
        "message": {"id": msg_obj.id, "role": "assistant", "content": text, "created_at": msg_obj.created_at.isoformat()},
    }, user_id)
