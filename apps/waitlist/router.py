"""Public early-access request endpoint (the marketing site's form)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from core import email as email_service
from core.config import settings
from core.database import get_db
from apps.waitlist import service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/waitlist", tags=["Waitlist"])


class AccessRequestIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    reason: str = Field(min_length=1, max_length=2000)
    # "yes" | "sometimes" | "no"
    will_help: str = Field(default="", max_length=20)
    # Honeypot: hidden in the form, so anything here means a bot.
    company: str = Field(default="", max_length=200)


@router.post("/request")
def request_access(
    data: AccessRequestIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """Join the early-access waitlist.

    Unauthenticated by necessity, so everything that could be abused is
    bounded: rate limits in `service.submit`, one row per email address, and
    the confirmation email only ever going to a brand-new address.
    """
    if data.company.strip():
        # Silently accept so bots learn nothing from the response.
        logger.info("Waitlist honeypot tripped for %s", data.email)
        return {"ok": True}

    try:
        row, is_new = service.submit(
            db,
            name=data.name,
            email=data.email,
            reason=data.reason,
            will_help=data.will_help,
            ip=service.client_ip(request),
        )
    except service.RateLimited as e:
        raise HTTPException(
            status_code=429,
            detail=e.reason,
            headers={"Retry-After": str(e.retry_after)},
        )

    if is_new:
        # Thank-you to the person, heads-up to us. Both best-effort: a mail
        # failure must not lose the request that's already safely in the DB.
        email_service.send_waitlist_confirmation(row.email, row.name)

        admin_to = (settings.ADMIN_EMAILS.split(",")[0] or "").strip()
        if admin_to:
            email_service.send_waitlist_admin_alert(
                admin_to, row.name, row.email, row.reason, row.will_help
            )
        else:
            logger.warning("ADMIN_EMAILS unset — no alert for waitlist #%s", row.id)

    return {"ok": True, "already_registered": not is_new}
