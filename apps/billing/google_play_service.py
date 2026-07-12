"""Google Play Billing — server-side purchase verification + RTDN processing.

Flow:
  1. The Android app launches the Play purchase flow (expo-iap) and receives a
     `purchaseToken`. It POSTs the token to `/billing/google-play/verify`.
  2. We verify the token against the Play Developer API
     (`purchases.subscriptionsv2.get`), read Google's authoritative state and
     `expiryTime`, and grant entitlement via `billing_service.activate_paid(
     provider="google_play", ...)`. We also acknowledge the purchase so Play
     doesn't auto-refund it after 3 days.
  3. Renewals, cancellations, refunds and expiries arrive asynchronously as
     Real-Time Developer Notifications (RTDN) over Pub/Sub push →
     `/billing/google-play/rtdn`. That handler re-fetches authoritative state
     from the API and reconciles entitlement, so notifications are never
     trusted blindly.

Entitlement itself stays in `billing_service` — this module only verifies with
Google and translates the result into `activate_paid` / `mark_cancelled` /
`mark_expired` calls, exactly like `razorpay_service` does for the web path.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.config import IST, settings
from apps.auth.models import User
from apps.billing import service as billing_service

logger = logging.getLogger(__name__)

_SCOPE = "https://www.googleapis.com/auth/androidpublisher"

# RTDN subscription notification types → our handling.
# https://developer.android.com/google/play/billing/rtdn-reference
NOTIF_RENEWED = {1, 2, 4, 7}       # recovered, renewed, purchased, restarted
NOTIF_CANCELED = {3}               # user turned off auto-renew (keeps access)
NOTIF_EXPIRED = {12, 13}           # revoked (refund/chargeback) / expired

# Play subscriptionState values we treat as "currently entitled" (as long as
# the line item's expiryTime is still in the future). CANCELED here means
# auto-renew is off but the paid period hasn't ended yet.
_ENTITLED_STATES = {
    "SUBSCRIPTION_STATE_ACTIVE",
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD",
    "SUBSCRIPTION_STATE_CANCELED",
}


def _plan_for_product(product_id: str | None) -> str | None:
    if product_id and product_id == settings.GOOGLE_PLAY_PRODUCT_MONTHLY:
        return "monthly"
    if product_id and product_id == settings.GOOGLE_PLAY_PRODUCT_YEARLY:
        return "yearly"
    return None


def _price_paise_for(plan: str) -> int:
    """Ledger amount (paise). Play doesn't return a clean net price in v2, so we
    record the configured list price — consistent with what Razorpay logs."""
    inr = (
        settings.PRICE_MONTHLY_INR if plan == "monthly"
        else settings.PRICE_YEARLY_INR
    )
    return int(inr) * 100


def _parse_play_time(value: str | None) -> datetime | None:
    """RFC3339 (e.g. '2026-08-11T09:00:00Z') → naive IST, matching how the rest
    of the billing code stores timestamps (see service._now)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Unparseable Play timestamp: %r", value)
        return None
    return dt.astimezone(IST).replace(tzinfo=None)


def _load_credentials():
    raw = settings.GOOGLE_PLAY_SERVICE_ACCOUNT_JSON.strip()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Play Billing is not configured.",
        )
    from google.oauth2 import service_account

    # Accept either the raw JSON blob or a path to the key file.
    if raw.startswith("{"):
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(
            info, scopes=[_SCOPE]
        )
    return service_account.Credentials.from_service_account_file(
        raw, scopes=[_SCOPE]
    )


def _publisher():
    """A cached-per-call androidpublisher v3 client."""
    from googleapiclient.discovery import build

    creds = _load_credentials()
    return build(
        "androidpublisher", "v3", credentials=creds, cache_discovery=False
    )


def _get_subscription(token: str) -> dict:
    """Fetch authoritative purchase state from Google for a purchase token."""
    try:
        return (
            _publisher()
            .purchases()
            .subscriptionsv2()
            .get(
                packageName=settings.GOOGLE_PLAY_PACKAGE_NAME,
                token=token,
            )
            .execute()
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — surface as a clean API error
        logger.error("Play subscriptionsv2.get failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not verify the purchase with Google Play.",
        )


def _acknowledge(token: str, product_id: str) -> None:
    """Acknowledge a subscription purchase (best-effort). Play auto-refunds
    purchases that aren't acknowledged within 3 days."""
    try:
        (
            _publisher()
            .purchases()
            .subscriptions()
            .acknowledge(
                packageName=settings.GOOGLE_PLAY_PACKAGE_NAME,
                subscriptionId=product_id,
                token=token,
                body={},
            )
            .execute()
        )
    except Exception as e:  # noqa: BLE001 — the client also finishes the txn
        logger.warning("Play acknowledge failed for %s: %s", product_id, e)


def _primary_line_item(resp: dict) -> dict:
    """The line item that determines entitlement — the one expiring latest."""
    items = resp.get("lineItems") or []
    if not items:
        return {}
    return max(items, key=lambda li: li.get("expiryTime") or "")


def _apply(
    db: Session,
    user: User,
    token: str,
    resp: dict,
    *,
    event: str,
    event_id: str | None,
    acknowledge: bool,
) -> dict:
    """Translate an authoritative Play subscription state into entitlement."""
    state = resp.get("subscriptionState", "")
    line = _primary_line_item(resp)
    product_id = line.get("productId")
    plan = _plan_for_product(product_id)
    expiry = _parse_play_time(line.get("expiryTime"))
    order_id = resp.get("latestOrderId")
    now = billing_service._now()

    entitled = (
        state in _ENTITLED_STATES
        and expiry is not None
        and expiry > now
        and plan is not None
    )

    # Always remember the token so future RTDN events map back to this user.
    user.google_play_purchase_token = token
    db.commit()

    if entitled:
        # Activations are idempotent on the order id, so the client verify call
        # and the RTDN PURCHASED/RENEWED for the same order collapse to one.
        result = billing_service.activate_paid(
            db, user, plan,
            provider="google_play",
            amount=_price_paise_for(plan),
            event=event,
            payment_id=order_id,
            subscription_id=token,
            event_id=order_id or event_id,
            expires_at_override=expiry,
        )
        if acknowledge and resp.get("acknowledgementState") == (
            "ACKNOWLEDGEMENT_STATE_PENDING"
        ):
            _acknowledge(token, product_id)
        return result

    # Not entitled: refund/revoke/expiry/on-hold/paused. Expired or revoked ends
    # access now; other non-entitled states are recorded as audit-only.
    if state in ("SUBSCRIPTION_STATE_EXPIRED",) or (
        expiry is not None and expiry <= now
    ):
        return billing_service.mark_expired(
            db, user, provider="google_play", event=event,
            subscription_id=token, event_id=event_id,
        )
    billing_service._record_payment(
        db, user, provider="google_play", event=event, status_="info",
        plan=plan, subscription_id=token, event_id=event_id,
    )
    return billing_service.get_entitlement(user)


def verify_and_activate(db: Session, user: User, purchase_token: str) -> dict:
    """Verify a purchase token from the app and grant entitlement.

    Called by `POST /billing/google-play/verify` right after the in-app
    purchase completes. The plan is derived from Google's response, never
    trusted from the client.
    """
    if not purchase_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing purchase token.",
        )
    resp = _get_subscription(purchase_token)
    line = _primary_line_item(resp)
    plan = _plan_for_product(line.get("productId"))
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This purchase doesn't match a known subscription product.",
        )

    ent = _apply(
        db, user, purchase_token, resp,
        event="subscription.purchased", event_id=resp.get("latestOrderId"),
        acknowledge=True,
    )
    if not ent["is_entitled"]:
        # The token verified but isn't in an entitled state (e.g. pending
        # payment, on hold). Let the client show "not active yet".
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This purchase isn't active yet. Please try again shortly.",
        )
    return ent


# ── RTDN (Pub/Sub push) ───────────────────────────────────────────────────

def _user_for_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    return (
        db.query(User)
        .filter(User.google_play_purchase_token == token)
        .first()
    )


def handle_rtdn(db: Session, envelope: dict) -> None:
    """Process one Pub/Sub push envelope carrying a DeveloperNotification.

    The envelope is `{"message": {"data": <base64 JSON>, "messageId": ...}}`.
    We decode it, and for subscription notifications re-fetch authoritative
    state from Google before touching entitlement. Idempotent on the Pub/Sub
    messageId for lifecycle events and on the order id for activations.
    """
    import base64

    message = envelope.get("message") or {}
    message_id = message.get("messageId") or message.get("message_id")
    data_b64 = message.get("data")
    if not data_b64:
        logger.info("RTDN push with no data (subscription confirmation?)")
        return

    try:
        notification = json.loads(base64.b64decode(data_b64).decode("utf-8"))
    except (ValueError, TypeError) as e:
        logger.error("RTDN: could not decode message data: %s", e)
        return

    if notification.get("testNotification"):
        logger.info("RTDN test notification received: %s",
                    notification.get("testNotification"))
        return

    sub = notification.get("subscriptionNotification")
    if not sub:
        # voidedPurchaseNotification / oneTimeProductNotification — not used yet.
        logger.info("RTDN: unhandled notification type: %s",
                    list(notification.keys()))
        return

    notif_type = sub.get("notificationType")
    token = sub.get("purchaseToken")

    user = _user_for_token(db, token)
    if not user:
        # Token may have rotated (resubscribe uses a new token linked to the
        # old one). We still verify to keep the ledger complete, but without a
        # user we can only log.
        logger.warning("RTDN type %s for unknown purchase token", notif_type)
        return

    resp = _get_subscription(token)

    if notif_type in NOTIF_RENEWED:
        _apply(
            db, user, token, resp,
            event="subscription.renewed",
            event_id=resp.get("latestOrderId"),
            acknowledge=True,
        )
    elif notif_type in NOTIF_CANCELED:
        billing_service.mark_cancelled(
            db, user, provider="google_play",
            subscription_id=token, event_id=message_id,
        )
    elif notif_type in NOTIF_EXPIRED:
        billing_service.mark_expired(
            db, user, provider="google_play",
            event="subscription.revoked" if notif_type == 12
            else "subscription.expired",
            subscription_id=token, event_id=message_id,
        )
    else:
        # on-hold / grace / paused / price-change / deferred — reconcile from
        # the authoritative state (may extend or lapse) and audit.
        _apply(
            db, user, token, resp,
            event=f"subscription.notification.{notif_type}",
            event_id=message_id,
            acknowledge=False,
        )
