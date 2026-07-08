"""Subscription entitlement logic.

Plans: monthly ₹149, yearly ₹1499, with a one-time 3-day free trial.

NOTE ON PAYMENTS: actual charging must go through Google Play Billing (the
mobile app owns the purchase flow). `activate_subscription` is the server-side
entitlement switch — in production it should be called from a Play purchase
verification endpoint, not trusted blindly from the client.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.config import IST, settings
from apps.auth.models import User

PLAN_DURATIONS = {
    "monthly": timedelta(days=30),
    "yearly": timedelta(days=365),
}


def _now() -> datetime:
    return datetime.now(IST).replace(tzinfo=None)


def get_entitlement(user: User) -> dict:
    """Compute the user's effective subscription state."""
    now = _now()

    # Paid subscription takes precedence.
    if user.subscription_expires_at and user.subscription_expires_at > now:
        return {
            "status": "active",
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


def activate_subscription(db: Session, user: User, plan: str) -> dict:
    """Activate (or extend) a paid plan for the user."""
    duration = PLAN_DURATIONS.get(plan)
    if duration is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown plan. Choose 'monthly' or 'yearly'.",
        )

    now = _now()
    # Extend from the current expiry if still active, otherwise from now.
    base = user.subscription_expires_at if (
        user.subscription_expires_at and user.subscription_expires_at > now
    ) else now

    user.subscription_plan = plan
    user.subscription_status = "active"
    user.subscription_expires_at = base + duration
    db.commit()
    db.refresh(user)
    return get_entitlement(user)
