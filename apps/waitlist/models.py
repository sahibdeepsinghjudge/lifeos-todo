"""Early-access waitlist — one row per request from the marketing site."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from core.config import IST
from core.database import Base


class AccessRequest(Base):
    __tablename__ = "access_requests"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    name: Mapped[str] = mapped_column(String(120))
    # Unique: one request per address. A repeat submission updates the
    # existing row instead of creating a duplicate (see service.submit).
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    reason: Mapped[str] = mapped_column(Text)
    # 'yes' | 'sometimes' | 'no' — how involved they want to be.
    will_help: Mapped[str] = mapped_column(String(20), default="")

    # 'pending' | 'onboarded' — toggled from the admin dashboard.
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    onboarded_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    # Truncated SHA-256 of the client IP, never the IP itself: enough to rate
    # limit and spot a flood, useless for tracking anyone.
    ip_hash: Mapped[str] = mapped_column(String(32), default="", index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(IST).replace(tzinfo=None), index=True
    )
