"""Subscription entitlement logic.

Plans: monthly ₹149, yearly ₹1499, with a one-time 3-day free trial.

NOTE ON PAYMENTS: actual charging must go through Google Play Billing (the
mobile app owns the purchase flow). `activate_subscription` is the server-side
entitlement switch — in production it should be called from a Play purchase
verification endpoint, not trusted blindly from the client.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.config import IST, settings
from core import email
from apps.auth.models import User
from apps.billing.models import Payment

logger = logging.getLogger(__name__)

PLAN_DURATIONS = {
    "monthly": timedelta(days=30),
    "yearly": timedelta(days=365),
}


def _now() -> datetime:
    return datetime.now(IST).replace(tzinfo=None)


def get_entitlement(user: User) -> dict:
    """Compute the user's effective subscription state."""
    now = _now()

    # Paid subscription takes precedence. A cancelled plan stays entitled
    # until the paid-for period ends, but is surfaced as "cancelled" so the
    # app can show "ends on X" instead of "renews on X".
    if user.subscription_expires_at and user.subscription_expires_at > now:
        return {
            "status": "cancelled"
            if user.subscription_status == "cancelled"
            else "active",
            "plan": user.subscription_plan,
            "expires_at": user.subscription_expires_at,
            "trial_available": False,
            "is_entitled": True,
        }

    # Trial window.
    if user.trial_started_at:
        trial_ends = user.trial_started_at + timedelta(days=settings.TRIAL_DAYS)
        if trial_ends > now:
            return {
                "status": "trial",
                "plan": None,
                "expires_at": trial_ends,
                "trial_available": False,
                "is_entitled": True,
            }
        # Trial used up (and no active sub).
        return {
            "status": "expired",
            "plan": None,
            "expires_at": None,
            "trial_available": False,
            "is_entitled": False,
        }

    return {
        "status": "none",
        "plan": None,
        "expires_at": None,
        "trial_available": True,
        "is_entitled": False,
    }


def start_trial(db: Session, user: User) -> dict:
    """Begin the one-time free trial."""
    ent = get_entitlement(user)
    if ent["is_entitled"]:
        return ent
    if user.trial_started_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your free trial has already been used.",
        )
    user.trial_started_at = _now()
    user.subscription_status = "trial"
    db.commit()
    db.refresh(user)
    return get_entitlement(user)


def _record_payment(
    db: Session,
    user: User,
    *,
    provider: str,
    event: str,
    plan: str | None = None,
    amount: int = 0,
    currency: str = "INR",
    status_: str = "success",
    payment_id: str | None = None,
    subscription_id: str | None = None,
    event_id: str | None = None,
) -> bool:
    """Append a ledger row. Returns False if this event_id was already seen
    (idempotent — webhook replays become no-ops)."""
    if event_id:
        seen = (
            db.query(Payment)
            .filter(Payment.provider_event_id == event_id)
            .first()
        )
        if seen:
            return False
    db.add(
        Payment(
            user_id=user.id,
            provider=provider,
            event=event,
            plan=plan,
            amount=amount,
            currency=currency,
            status=status_,
            provider_payment_id=payment_id,
            provider_subscription_id=subscription_id,
            provider_event_id=event_id,
        )
    )
    db.commit()
    return True


def activate_paid(
    db: Session,
    user: User,
    plan: str,
    *,
    provider: str,
    amount: int = 0,
    currency: str = "INR",
    event: str = "payment.captured",
    payment_id: str | None = None,
    subscription_id: str | None = None,
    event_id: str | None = None,
    send_receipt: bool = True,
) -> dict:
    """Grant/extend a paid plan from a verified payment (any provider).

    Idempotent on `event_id`. Records the payment, extends entitlement, resets
    the expiry-reminder flag for the new cycle, and emails a receipt.
    """
    duration = PLAN_DURATIONS.get(plan)
    if duration is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown plan. Choose 'monthly' or 'yearly'.",
        )

    fresh = _record_payment(
        db, user,
        provider=provider, event=event, plan=plan, amount=amount,
        currency=currency, payment_id=payment_id,
        subscription_id=subscription_id, event_id=event_id,
    )
    if not fresh:
        # Already processed this event — return current state unchanged.
        return get_entitlement(user)

    now = _now()
    base = user.subscription_expires_at if (
        user.subscription_expires_at and user.subscription_expires_at > now
    ) else now

    user.subscription_plan = plan
    user.subscription_status = "active"
    user.subscription_provider = provider
    user.subscription_expires_at = base + duration
    user.expiry_reminder_sent_at = None  # fresh cycle → allow a new reminder
    db.commit()
    db.refresh(user)

    if send_receipt:
        email.send_payment_success(
            user.email, user.name, plan, amount // 100 if amount else 0,
            user.subscription_expires_at,
        )
    return get_entitlement(user)


def mark_cancelled(
    db: Session,
    user: User,
    *,
    provider: str,
    subscription_id: str | None = None,
    event_id: str | None = None,
) -> dict:
    """Record a cancellation. Entitlement is left to lapse naturally at expiry
    (the user keeps Pro until subscription_expires_at)."""
    fresh = _record_payment(
        db, user,
        provider=provider, event="subscription.cancelled", status_="info",
        plan=user.subscription_plan, subscription_id=subscription_id,
        event_id=event_id,
    )
    if not fresh:
        return get_entitlement(user)

    user.subscription_status = "cancelled"
    db.commit()
    db.refresh(user)
    email.send_subscription_cancelled(
        user.email, user.name, user.subscription_expires_at
    )
    return get_entitlement(user)


def activate_subscription(db: Session, user: User, plan: str) -> dict:
    """Manual/dev activation (no real payment). Kept for the current mobile
    /billing/subscribe path until Google Play Billing verification lands."""
    return activate_paid(
        db, user, plan, provider="manual", event="manual.grant",
        send_receipt=False,
    )


def admin_stats(db: Session) -> dict:
    """Subscription + revenue snapshot for the admin dashboard."""
    from sqlalchemy import func

    now = _now()
    total_users = db.query(func.count(User.id)).scalar() or 0
    active = (
        db.query(func.count(User.id))
        .filter(
            User.subscription_expires_at.isnot(None),
            User.subscription_expires_at > now,
        )
        .scalar()
        or 0
    )
    on_trial = (
        db.query(func.count(User.id))
        .filter(
            User.trial_started_at.isnot(None),
            (User.subscription_expires_at.is_(None))
            | (User.subscription_expires_at <= now),
        )
        .scalar()
        or 0
    )
    # Trials still inside the window are counted as trial, not expired.
    trial_window = now - timedelta(days=settings.TRIAL_DAYS)
    on_trial = (
        db.query(func.count(User.id))
        .filter(
            User.trial_started_at.isnot(None),
            User.trial_started_at > trial_window,
            (User.subscription_expires_at.is_(None))
            | (User.subscription_expires_at <= now),
        )
        .scalar()
        or 0
    )

    # Revenue from the ledger (paise → rupees), successful charges only.
    gross_paise = (
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.status == "success")
        .scalar()
        or 0
    )
    plan_split = dict(
        db.query(User.subscription_plan, func.count(User.id))
        .filter(
            User.subscription_expires_at.isnot(None),
            User.subscription_expires_at > now,
        )
        .group_by(User.subscription_plan)
        .all()
    )
    return {
        "total_users": int(total_users),
        "active_subscribers": int(active),
        "on_trial": int(on_trial),
        "gross_revenue_inr": int(gross_paise) // 100,
        "monthly_active": int(plan_split.get("monthly", 0)),
        "yearly_active": int(plan_split.get("yearly", 0)),
    }


def recent_payments(db: Session, limit: int = 20) -> list[dict]:
    """Latest ledger rows joined to the user, for the dashboard table."""
    rows = (
        db.query(Payment, User.email)
        .join(User, User.id == Payment.user_id)
        .order_by(Payment.created_at.desc())
        .limit(limit)
        .all()
    )
    out = []
    for p, em in rows:
        out.append(
            {
                "created_at": p.created_at.strftime("%d %b %H:%M"),
                "email": em,
                "provider": p.provider,
                "event": p.event,
                "plan": p.plan or "—",
                "amount_inr": (p.amount or 0) // 100,
                "status": p.status,
            }
        )
    return out


def send_expiry_reminders(db: Session) -> int:
    """Email users whose paid plan expires within EXPIRY_REMINDER_DAYS and who
    haven't already been reminded this cycle. Returns how many were sent.

    Idempotent within a cycle via `expiry_reminder_sent_at`, which is cleared
    whenever a fresh payment extends the subscription (see activate_paid)."""
    now = _now()
    window_end = now + timedelta(days=settings.EXPIRY_REMINDER_DAYS)

    due = (
        db.query(User)
        .filter(
            User.subscription_expires_at.isnot(None),
            User.subscription_expires_at > now,
            User.subscription_expires_at <= window_end,
            User.expiry_reminder_sent_at.is_(None),
        )
        .all()
    )

    sent = 0
    renew_url = f"{settings.WEBSITE_URL}/#pricing"
    for user in due:
        days_left = max(1, (user.subscription_expires_at - now).days)
        ok = email.send_expiry_reminder(
            user.email, user.name, days_left,
            user.subscription_expires_at, renew_url,
        )
        if ok:
            user.expiry_reminder_sent_at = now
            db.commit()
            sent += 1
    if sent:
        logger.info("Sent %d expiry reminder(s)", sent)
    return sent
