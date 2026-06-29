from datetime import datetime

from sqlalchemy import String, ForeignKey, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.config import IST
from core.database import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(IST))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(IST),
        onupdate=lambda: datetime.now(IST),
    )

    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", lazy="selectin")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # 'user', 'assistant', 'tool'
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Store tool calls as JSON
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(IST))

    session: Mapped["ChatSession"] = relationship(back_populates="messages")
