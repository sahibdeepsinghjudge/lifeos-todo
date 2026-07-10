"""Billing endpoints — plans, entitlement status, trial, and activation."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.config import settings
from core.database import get_db
from core.security import get_current_user
from apps.auth.models import User
from apps.billing import service
from apps.billing import razorpay_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["Billing"])


class EntitlementResponse(BaseModel):
    status: str  # none | trial | active | expired
    plan: str | None
    expires_at: datetime | None
    trial_available: bool
    is_entitled: bool


class SubscribeRequest(BaseModel):
    plan: str  # 'monthly' | 'yearly'
    # Play Billing purchase token — verified server-side once Play Billing is
    # wired up. Accepted now so the client contract doesn't change later.
    purchase_token: str | None = None


@router.get("/plans")
def get_plans():
    return {
        "trial_days": settings.TRIAL_DAYS,
        "plans": [
            {
                "id": "monthly",
                "label": "Monthly",
                "price_inr": settings.PRICE_MONTHLY_INR,
                "period": "month",
            },
            {
                "id": "yearly",
                "label": "Yearly",
                "price_inr": settings.PRICE_YEARLY_INR,
                "period": "year",
            },
        ],
    }


@router.get("/status", response_model=EntitlementResponse)
def get_status(user: User = Depends(get_current_user)):
    return service.get_entitlement(user)


@router.post("/start-trial", response_model=EntitlementResponse)
def start_trial(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.start_trial(db, user)


@router.post("/subscribe", response_model=EntitlementResponse)
def subscribe(
    data: SubscribeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # TODO(play-billing): verify data.purchase_token against the Google Play
    # Developer API before activating, once store products exist. Until then
    # this is a manual/dev grant (no real charge).
    return service.activate_subscription(db, user, data.plan)


# ── Razorpay (web subscriptions) ──────────────────────────────────────────

class RazorpaySubscribeRequest(BaseModel):
    plan: str  # 'monthly' | 'yearly'


@router.post("/razorpay/subscription")
def create_razorpay_subscription(
    data: RazorpaySubscribeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a Razorpay subscription and return its hosted checkout URL.

    The web client redirects the user to `short_url` to complete payment;
    entitlement is granted later by the webhook, not here.
    """
    return razorpay_service.create_subscription(db, user, data.plan)


@router.post("/razorpay/webhook")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
    x_razorpay_event_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Razorpay → us. Signature-verified; drives all entitlement changes."""
    body = await request.body()
    if not razorpay_service.verify_webhook_signature(body, x_razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid payload")

    event_type = payload.get("event", "")
    try:
        razorpay_service.handle_webhook_event(
            db, event_type, payload.get("payload") or {}, x_razorpay_event_id
        )
    except Exception as e:  # noqa: BLE001 — always 200 so Razorpay stops retrying a poison event
        logger.error("Razorpay webhook '%s' failed: %s", event_type, e)

    # Acknowledge receipt regardless — we've logged failures for replay.
    return {"status": "ok"}
