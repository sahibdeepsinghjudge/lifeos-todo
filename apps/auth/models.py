from __future__ import annotations

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from core.config import IST
from core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    preferences: Mapped[str | None] = mapped_column(String, nullable=True)
    # 'password' or 'google'
    auth_provider: Mapped[str] = mapped_column(String(20), default="password")
    # Billing: 'none' | 'trial' | 'active' — effective entitlement is computed
    # from these fields (see apps.billing.service.get_entitlement).
    subscription_status: Mapped[str] = mapped_column(String(20), default="none")
    subscription_plan: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 'monthly' | 'yearly'
    trial_started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    subscription_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(IST)
    )

