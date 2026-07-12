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
from apps.billing import google_play_service
from apps.usage import service as usage_service

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


@router.post("/cancel", response_model=EntitlementResponse)
def cancel_subscription(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Cancel the caller's paid subscription. Access continues until the end
    of the already-paid period; nothing renews after that."""
    ent = service.get_entitlement(user)
    if ent["status"] == "cancelled":
        return ent  # idempotent — already cancelled
    if ent["status"] != "active":
        raise HTTPException(
            status_code=400,
            detail="You don't have an active subscription to cancel.",
        )

    # Stop future charges at the provider first (best-effort; the webhook
    # reconciles), then record the cancellation locally.
    razorpay_service.cancel_provider_subscription(user)
    return service.mark_cancelled(
        db, user, provider=user.subscription_provider or "manual"
    )


@router.get("/usage")
def get_my_usage(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The caller's own AI token usage — 30-day totals plus a per-day
    input/output breakdown, shown in the app's OttoAI Pro settings."""
    return usage_service.user_summary(db, user.id, days=30)


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


# ── Google Play (Android in-app subscriptions) ────────────────────────────

class GooglePlayVerifyRequest(BaseModel):
    # The purchaseToken from the completed Play Billing purchase. The plan is
    # derived server-side from Google's response, not trusted from the client.
    purchase_token: str
    product_id: str | None = None  # informational only


@router.post("/google-play/verify", response_model=EntitlementResponse)
def google_play_verify(
    data: GooglePlayVerifyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Verify a Play purchase token and grant entitlement to the caller.

    The app calls this right after the in-app purchase completes. Entitlement
    is granted only if Google confirms the subscription is active.
    """
    return google_play_service.verify_and_activate(db, user, data.purchase_token)


@router.post("/google-play/rtdn")
async def google_play_rtdn(
    request: Request,
    token: str | None = None,
    db: Session = Depends(get_db),
):
    """Google Play Real-Time Developer Notifications via Pub/Sub push.

    Configure the Pub/Sub push endpoint as
    `…/billing/google-play/rtdn?token=<GOOGLE_PLAY_RTDN_VERIFICATION_TOKEN>`
    so only Google's push can reach it. Always returns 200 so Pub/Sub stops
    redelivering a poison message (failures are logged for replay).
    """
    expected = settings.GOOGLE_PLAY_RTDN_VERIFICATION_TOKEN
    if expected and token != expected:
        raise HTTPException(status_code=403, detail="Invalid RTDN token")

    try:
        envelope = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid payload")

    try:
        google_play_service.handle_rtdn(db, envelope)
    except Exception as e:  # noqa: BLE001 — never make Pub/Sub retry forever
        logger.error("Google Play RTDN handling failed: %s", e)

    return {"status": "ok"}
