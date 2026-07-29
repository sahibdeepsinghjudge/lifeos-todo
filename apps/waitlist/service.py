"""Waitlist intake — persistence plus the abuse limits guarding a public form.

The form is unauthenticated, so it is the one endpoint anyone on the internet
can make us do work for: a DB write and an outbound email. Three layers guard
it, cheapest first:

  1. An in-process sliding window rejects floods before touching the DB. It's
     per-worker and resets on deploy, which is fine — it exists to absorb
     bursts, not to be authoritative.
  2. DB-backed per-IP counts over the last hour/day survive restarts and are
     shared across workers, so they're the real limit.
  3. A global hourly cap bounds total damage (and our Resend bill) even from
     a distributed flood across many IPs.

Email addresses are deduped rather than rejected: a repeat submission updates
the existing row and sends no second email.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from core.config import IST
from apps.waitlist.models import AccessRequest

logger = logging.getLogger(__name__)

# ── limits ────────────────────────────────────────────────────────────────
BURST_MAX = 5              # per IP, within BURST_WINDOW_S (in-process)
BURST_WINDOW_S = 60
PER_IP_HOURLY = 3          # per IP, last 60 min (DB)
PER_IP_DAILY = 8           # per IP, last 24 h (DB)
GLOBAL_HOURLY = 200        # everyone combined, last 60 min (DB)

# ip_hash -> recent request timestamps (monotonic seconds)
_burst: dict[str, deque[float]] = defaultdict(deque)
# Stop the burst map growing without bound on a long-lived process.
_MAX_TRACKED_IPS = 10_000


class RateLimited(Exception):
    """Raised when a submission trips any abuse limit."""

    def __init__(self, reason: str, retry_after: int = 3600):
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


def hash_ip(ip: str) -> str:
    """Truncated SHA-256 — enough to group requests, not enough to identify."""
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:32]


def client_ip(request) -> str:
    """Real client IP behind Render's proxy.

    X-Forwarded-For is client, proxy1, proxy2... so the client is the first
    entry. It's spoofable, which is exactly why it only ever feeds rate
    limiting (worst case an attacker rotates the header and falls through to
    the global cap) and is hashed before storage.
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_burst(ip_hash: str) -> None:
    now = time.monotonic()
    q = _burst[ip_hash]
    while q and now - q[0] > BURST_WINDOW_S:
        q.popleft()
    if len(q) >= BURST_MAX:
        raise RateLimited("Too many attempts. Try again in a minute.", 60)
    q.append(now)

    if len(_burst) > _MAX_TRACKED_IPS:
        for k in [k for k, v in _burst.items() if not v or now - v[-1] > BURST_WINDOW_S]:
            _burst.pop(k, None)


def _now() -> datetime:
    return datetime.now(IST).replace(tzinfo=None)


def _check_db_limits(db: Session, ip_hash: str) -> None:
    now = _now()

    hourly = (
        db.query(func.count(AccessRequest.id))
        .filter(
            AccessRequest.ip_hash == ip_hash,
            AccessRequest.created_at > now - timedelta(hours=1),
        )
        .scalar()
    ) or 0
    if hourly >= PER_IP_HOURLY:
        raise RateLimited("You've already sent a few requests. Try again later.")

    daily = (
        db.query(func.count(AccessRequest.id))
        .filter(
            AccessRequest.ip_hash == ip_hash,
            AccessRequest.created_at > now - timedelta(days=1),
        )
        .scalar()
    ) or 0
    if daily >= PER_IP_DAILY:
        raise RateLimited("Daily limit reached. Try again tomorrow.", 86400)

    total = (
        db.query(func.count(AccessRequest.id))
        .filter(AccessRequest.created_at > now - timedelta(hours=1))
        .scalar()
    ) or 0
    if total >= GLOBAL_HOURLY:
        logger.warning("Waitlist global hourly cap hit (%s requests)", total)
        raise RateLimited("We're getting a lot of requests right now. Try again soon.")


def submit(
    db: Session,
    *,
    name: str,
    email: str,
    reason: str,
    will_help: str,
    ip: str,
) -> tuple[AccessRequest, bool]:
    """Record a request. Returns (row, is_new).

    is_new is False when this address already applied — the caller uses it to
    skip the confirmation email so a resubmit can't be used to mailbomb
    someone else's address.
    """
    ih = hash_ip(ip)
    _check_burst(ih)
    _check_db_limits(db, ih)

    email = email.strip().lower()
    existing = (
        db.query(AccessRequest).filter(AccessRequest.email == email).first()
    )
    if existing:
        # Let them correct what they wrote, but never reset their place in the
        # queue and never re-notify.
        existing.name = name.strip()
        existing.reason = reason.strip()
        existing.will_help = will_help
        db.commit()
        db.refresh(existing)
        return existing, False

    row = AccessRequest(
        name=name.strip(),
        email=email,
        reason=reason.strip(),
        will_help=will_help,
        ip_hash=ih,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, True


# ── admin reads / writes ──────────────────────────────────────────────────

def list_requests(db: Session, limit: int = 200) -> list[AccessRequest]:
    return (
        db.query(AccessRequest)
        .order_by(AccessRequest.created_at.desc())
        .limit(limit)
        .all()
    )


def stats(db: Session) -> dict:
    total = db.query(func.count(AccessRequest.id)).scalar() or 0
    onboarded = (
        db.query(func.count(AccessRequest.id))
        .filter(AccessRequest.status == "onboarded")
        .scalar()
    ) or 0
    day = (
        db.query(func.count(AccessRequest.id))
        .filter(AccessRequest.created_at > _now() - timedelta(days=1))
        .scalar()
    ) or 0
    return {
        "total": total,
        "onboarded": onboarded,
        "pending": total - onboarded,
        "last_24h": day,
    }


def toggle_onboarded(db: Session, request_id: int) -> AccessRequest | None:
    row = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if not row:
        return None
    if row.status == "onboarded":
        row.status = "pending"
        row.onboarded_at = None
    else:
        row.status = "onboarded"
        row.onboarded_at = _now()
    db.commit()
    db.refresh(row)
    return row
