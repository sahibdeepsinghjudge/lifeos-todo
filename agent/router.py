from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.database import get_db
from core.security import get_current_user, decode_access_token
from apps.auth.models import User
from agent.orchestrator import run_agent_async
from agent.models import ChatSession, ChatMessage
from agent.ws_manager import manager
import json
import asyncio
from sqlalchemy import or_, and_

router = APIRouter(prefix="/agent", tags=["Agent"])


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    actions: list[dict] = []


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str | None
    tool_calls: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str, db: Session = Depends(get_db)):
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub"))
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await websocket.close(code=1008)
            return
    except Exception:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg_data = json.loads(data)
                if "message" in msg_data:
                    user_message = msg_data["message"]
                    
                    async def run_agent_wrapper():
                        try:
                            await asyncio.wait_for(run_agent_async(db, user_id, user_message), timeout=60.0)
                        except asyncio.TimeoutError:
                            await manager.send_personal_message({"type": "error", "message": "The agent timed out while processing your request."}, user_id)
                        except Exception as e:
                            await manager.send_personal_message({"type": "error", "message": f"An error occurred: {str(e)}"}, user_id)

                    # Fire off the agent processing asynchronously
                    asyncio.create_task(run_agent_wrapper())
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)


@router.get("/history", response_model=list[MessageResponse])
def get_history(
    limit: int = 5,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[MessageResponse]:
    session = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
        .first()
    )
    if not session:
        return []
    
    # Fetch descending (newest first) with limit and offset, filtering out tool noise
    messages_desc = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == session.id,
            ChatMessage.role.in_(["user", "assistant"]),
            or_(
                ChatMessage.role == "user",
                and_(ChatMessage.role == "assistant", ChatMessage.content != None, ChatMessage.content != "")
            )
        )
        .order_by(ChatMessage.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    
    # Reverse back to chronological order (oldest first)
    return messages_desc[::-1]


@router.delete("/history")
def clear_history(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    session = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
        .first()
    )
    if session:
        db.query(ChatMessage).filter(ChatMessage.session_id == session.id).delete()
        db.delete(session)
        db.commit()
    return {"detail": "Chat history cleared"}
