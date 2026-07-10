"""Razorpay web subscriptions + webhook processing.

Flow:
  1. Web client calls POST /billing/razorpay/subscription → we create a
     Razorpay subscription and return its hosted `short_url` to redirect to.
  2. Razorpay charges the card and calls our webhook. The webhook is the
     source of truth: on `subscription.charged` we extend entitlement and
     email a receipt; on cancel/halt we record it and email the user.

Google Play Billing (the in-app path) will slot in as a second provider that
also calls `billing_service.activate_paid(..., provider="google_play")`, so
entitlement logic stays in one place.
"""

from __future__ import annotations

import hmac
import hashlib
import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.config import settings
from apps.auth.models import User
from apps.billing import service as billing_service

logger = logging.getLogger(__name__)

# Billing cycles to schedule per plan (Razorpay requires total_count).
_TOTAL_COUNT = {"monthly": 120, "yearly": 10}  # ~10 years either way


def _plan_id_for(plan: str) -> str:
    mapping = {
        "monthly": settings.RAZORPAY_PLAN_MONTHLY,
        "yearly": settings.RAZORPAY_PLAN_YEARLY,
    }
    plan_id = mapping.get(plan)
    if not plan_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No Razorpay plan configured for '{plan}'.",
        )
    return plan_id


def _plan_from_id(plan_id: str | None) -> str | None:
    if plan_id and plan_id == settings.RAZORPAY_PLAN_MONTHLY:
        return "monthly"
    if plan_id and plan_id == settings.RAZORPAY_PLAN_YEARLY:
        return "yearly"
    return None


def _client():
    if not (settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Razorpay is not configured.",
        )
    import razorpay

    return razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )


def create_subscription(db: Session, user: User, plan: str) -> dict:
    """Create a Razorpay subscription for the user; return its checkout URL."""
    plan_id = _plan_id_for(plan)
    client = _client()

    sub = client.subscription.create(
        {
            "plan_id": plan_id,
            "total_count": _TOTAL_COUNT.get(plan, 12),
            "customer_notify": 1,
            "notes": {"user_id": str(user.id), "app_plan": plan},
        }
    )

    # Remember the subscription id so the webhook can map events back here.
    user.razorpay_subscription_id = sub["id"]
    db.commit()

    return {
        "subscription_id": sub["id"],
        "short_url": sub.get("short_url"),
        "key_id": settings.RAZORPAY_KEY_ID,
        "plan": plan,
    }


def verify_webhook_signature(body: bytes, signature: str | None) -> bool:
    """HMAC-SHA256 verify a Razorpay webhook against RAZORPAY_WEBHOOK_SECRET."""
    secret = settings.RAZORPAY_WEBHOOK_SECRET
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _user_for_subscription(
    db: Session, sub_id: str | None, sub_entity: dict
) -> User | None:
    if sub_id:
        user = (
            db.query(User)
            .filter(User.razorpay_subscription_id == sub_id)
            .first()
        )
        if user:
            return user
    # Fall back to the user_id we stamped into notes at creation time.
    notes = sub_entity.get("notes") or {}
    uid = notes.get("user_id")
    if uid:
        try:
            return db.query(User).filter(User.id == int(uid)).first()
        except (TypeError, ValueError):
            return None
    return None


def handle_webhook_event(
    db: Session, event_type: str, payload: dict, event_id: str | None
) -> None:
    """Apply one verified webhook event to entitlement + ledger."""
    sub_entity = (payload.get("subscription") or {}).get("entity") or {}
    sub_id = sub_entity.get("id")
    plan = _plan_from_id(sub_entity.get("plan_id"))

    user = _user_for_subscription(db, sub_id, sub_entity)
    if not user:
        logger.warning("Razorpay webhook '%s' for unknown subscription %s",
                       event_type, sub_id)
        return

    if event_type == "subscription.charged":
        if not plan:
            logger.warning("charged event with unmapped plan_id on sub %s", sub_id)
            return
        pay_entity = (payload.get("payment") or {}).get("entity") or {}
        billing_service.activate_paid(
            db, user, plan,
            provider="razorpay",
            amount=pay_entity.get("amount", 0),
            currency=pay_entity.get("currency", "INR"),
            event=event_type,
            payment_id=pay_entity.get("id"),
            subscription_id=sub_id,
            event_id=event_id,
        )
    elif event_type in (
        "subscription.cancelled",
        "subscription.halted",
        "subscription.completed",
    ):
        billing_service.mark_cancelled(
            db, user, provider="razorpay",
            subscription_id=sub_id, event_id=event_id,
        )
    else:
        # activated / authenticated / pending / updated — audit only.
        billing_service._record_payment(
            db, user, provider="razorpay", event=event_type, status_="info",
            plan=plan, subscription_id=sub_id, event_id=event_id,
        )
