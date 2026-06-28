from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.database import get_db
from core.security import get_current_user
from apps.auth.models import User
from agent.orchestrator import run_agent, get_or_create_session
from agent.models import ChatSession, ChatMessage

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


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    result = run_agent(db, user.id, body.message)
    return ChatResponse(**result)


@router.get("/history", response_model=list[MessageResponse])
def get_history(
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
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    return messages


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
