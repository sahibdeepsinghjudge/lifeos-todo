"""Billing endpoints — plans, entitlement status, trial, and activation."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.config import settings
from core.database import get_db
from core.security import get_current_user
from apps.auth.models import User
from apps.billing import service

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
    # Developer API before activating, once store products exist.
    return service.activate_subscription(db, user, data.plan)
