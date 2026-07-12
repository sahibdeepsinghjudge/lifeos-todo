from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import String, Boolean, Date, Integer
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
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    preferences: Mapped[str | None] = mapped_column(String, nullable=True)
    # 'password' or 'google'
    auth_provider: Mapped[str] = mapped_column(String(20), default="password")
    # Email OTP verification. New password signups start unverified and must
    # confirm a 6-digit code emailed to them; Google users are verified by
    # Google. The code is stored hashed, expires quickly, and allows only a
    # few attempts before a fresh code is required.
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_otp_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_otp_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    email_otp_attempts: Mapped[int] = mapped_column(default=0)
    email_otp_sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Billing: 'none' | 'trial' | 'active' — effective entitlement is computed
    # from these fields (see apps.billing.service.get_entitlement).
    subscription_status: Mapped[str] = mapped_column(String(20), default="none")
    subscription_plan: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 'monthly' | 'yearly'
    # Which processor the current paid entitlement came through:
    # 'razorpay' | 'google_play' | 'trial' | 'manual' | None.
    subscription_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    trial_started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    subscription_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Provider handles so webhooks can map an event back to a user.
    razorpay_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    razorpay_subscription_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    # Google Play: the latest subscription purchase token for this user. It is
    # stable across auto-renewals, so RTDN events (which carry only the token)
    # can be mapped back to the user here.
    google_play_purchase_token: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    # When we last emailed this user that their subscription is about to
    # expire, so the daily job never double-sends within the same cycle.
    expiry_reminder_sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Daily-use streak: +1 point per AI interaction, but continuity is daily —
    # a full calendar day (IST) with no interaction breaks the streak. The
    # reset happens lazily on the next interaction (see usage.record_streak),
    # so while broken, streak_count still holds the frozen previous streak.
    streak_count: Mapped[int] = mapped_column(Integer, default=0)
    streak_prev: Mapped[int] = mapped_column(Integer, default=0)
    streak_last_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(IST)
    )

    @property
    def streak_is_broken(self) -> bool:
        """True when an earned streak has gone cold — no AI interaction
        yesterday or today (IST). Read by UserResponse via from_attributes."""
        if self.streak_last_date is None or self.streak_count <= 0:
            return False
        return self.streak_last_date < datetime.now(IST).date() - timedelta(days=1)

