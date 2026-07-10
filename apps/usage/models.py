"""Per-turn LLM token usage, one row per agent turn.

Kept granular (not pre-aggregated) so the admin dashboard can roll up by day,
user, or model however it likes. Rows are cheap and write-once.
"""

from __future__ import annotations

from datetime import datetime, date

from sqlalchemy import Integer, String, ForeignKey, Date
from sqlalchemy.orm import Mapped, mapped_column

from core.config import IST
from core.database import Base


class TokenUsage(Base):
    __tablename__ = "token_usage"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    model: Mapped[str] = mapped_column(String(80), default="")

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)

    # Denormalized date (IST) for fast GROUP BY in the dashboard.
    usage_date: Mapped[date] = mapped_column(
        Date, index=True, default=lambda: datetime.now(IST).date()
    )
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(IST))
