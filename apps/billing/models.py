"""Billing ledger — an append-only record of payment/subscription events.

Every lifecycle event from any provider (Razorpay now, Google Play later)
lands here as a row. Entitlement itself lives on the User; this table is the
audit trail + revenue source for the admin dashboard.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from core.config import IST
from core.database import Base


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # 'razorpay' | 'google_play' | 'manual'
    provider: Mapped[str] = mapped_column(String(20))
    # Provider event that produced this row, e.g. 'subscription.charged',
    # 'subscription.cancelled', 'order.paid', 'manual.grant'.
    event: Mapped[str] = mapped_column(String(50))
    # 'monthly' | 'yearly' | None
    plan: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Money is stored in the smallest unit (paise) to avoid float drift.
    amount: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    # 'success' | 'failed' | 'refunded' | 'info'
    status: Mapped[str] = mapped_column(String(20), default="success")

    # Provider references for reconciliation / idempotency.
    provider_payment_id: Mapped[str | None] = mapped_column(
        String(80), nullable=True, index=True
    )
    provider_subscription_id: Mapped[str | None] = mapped_column(
        String(80), nullable=True, index=True
    )
    # Unique provider event id — a UNIQUE index makes webhook replays a no-op.
    provider_event_id: Mapped[str | None] = mapped_column(
        String(120), nullable=True, unique=True
    )

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(IST))
