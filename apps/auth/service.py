from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.auth.models import User
from apps.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
)
from core import email as email_service
from core.config import IST, settings
from core.security import create_access_token, hash_password, verify_password

logger = logging.getLogger(__name__)

# ── Email OTP verification ───────────────────────────────────────────────────

OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SECONDS = 60


def _now() -> datetime:
    return datetime.now(IST).replace(tzinfo=None)


def _issue_email_otp(db: Session, user: User) -> bool:
    """Generate, store (hashed) and email a fresh 6-digit code.

    Returns False when the email could not be sent (e.g. Resend not
    configured in dev) — callers decide how to degrade.
    """
    code = f"{secrets.randbelow(1_000_000):06d}"
    user.email_otp_hash = hash_password(code)
    user.email_otp_expires_at = _now() + timedelta(minutes=OTP_TTL_MINUTES)
    user.email_otp_attempts = 0
    user.email_otp_sent_at = _now()
    db.commit()
    return email_service.send_verification_otp(user.email, user.name, code)


def register_user(db: Session, data: RegisterRequest) -> User:
    existing = db.execute(
        select(User).where(User.email == data.email)
    ).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists. Please log in instead.",
        )

    user = User(
        name=data.name,
        email=data.email,
        hashed_password=hash_password(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Kick off email verification. If the email genuinely can't be sent
    # (no RESEND_API_KEY in dev, provider outage), auto-verify instead of
    # stranding the account behind a code that will never arrive.
    if not _issue_email_otp(db, user):
        logger.warning(
            "OTP email could not be sent to %s — auto-verifying.", user.email
        )
        user.email_verified = True
        user.email_otp_hash = None
        user.email_otp_expires_at = None
        db.commit()
        db.refresh(user)
    return user


def verify_email_otp(db: Session, email: str, code: str) -> TokenResponse:
    """Check a 6-digit code and, on success, verify the email and log in."""
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found for this email.",
        )

    if user.email_verified:
        # Already verified (e.g. double-tap) — just log them in.
        return TokenResponse(access_token=create_access_token(data={"sub": str(user.id)}))

    if not user.email_otp_hash or not user.email_otp_expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No verification code is active. Please request a new one.",
        )
    if user.email_otp_expires_at < _now():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That code has expired. Please request a new one.",
        )
    if user.email_otp_attempts >= OTP_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Too many incorrect attempts. Please request a new code.",
        )

    if not verify_password(code, user.email_otp_hash):
        user.email_otp_attempts += 1
        db.commit()
        remaining = OTP_MAX_ATTEMPTS - user.email_otp_attempts
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Incorrect code. {remaining} "
                f"{'attempt' if remaining == 1 else 'attempts'} left."
                if remaining > 0
                else "Too many incorrect attempts. Please request a new code."
            ),
        )

    user.email_verified = True
    user.email_otp_hash = None
    user.email_otp_expires_at = None
    user.email_otp_attempts = 0
    db.commit()

    email_service.send_welcome(user.email, user.name)
    return TokenResponse(access_token=create_access_token(data={"sub": str(user.id)}))


def resend_email_otp(db: Session, email: str) -> None:
    """Send a fresh code, with a short cooldown to stop hammering."""
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found for this email.",
        )
    if user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This email is already verified. Please log in.",
        )
    if (
        user.email_otp_sent_at
        and (_now() - user.email_otp_sent_at).total_seconds()
        < OTP_RESEND_COOLDOWN_SECONDS
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Please wait a minute before requesting another code.",
        )
    if not _issue_email_otp(db, user):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="We couldn't send the email right now. Please try again shortly.",
        )


def authenticate_user(db: Session, data: LoginRequest) -> TokenResponse:
    user = db.execute(
        select(User).where(User.email == data.email)
    ).scalar_one_or_none()

    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The email or password you entered is incorrect. Please try again.",
        )

    if not user.email_verified:
        # The client matches on this exact phrase to route to the OTP screen.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email to continue.",
        )

    token = create_access_token(data={"sub": str(user.id)})
    return TokenResponse(access_token=token)


def change_password(
    db: Session, user: User, data: ChangePasswordRequest
) -> None:
    if not verify_password(data.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your current password was entered incorrectly.",
        )

    user.hashed_password = hash_password(data.new_password)
    db.commit()


def deactivate_user(db: Session, user: User) -> None:
    user.is_active = False
    db.commit()


# ── Google Sign-In ───────────────────────────────────────────────────────────

GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


async def _verify_google_id_token(id_token: str) -> dict:
    """Validate a Google ID token via Google's tokeninfo endpoint.

    Returns the token claims (email, name, sub, aud, ...) or raises 401.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(GOOGLE_TOKENINFO_URL, params={"id_token": id_token})

    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google sign-in failed: invalid token.",
        )

    claims = resp.json()

    if claims.get("email_verified") not in ("true", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google sign-in failed: email not verified.",
        )

    allowed = [c.strip() for c in settings.GOOGLE_CLIENT_IDS.split(",") if c.strip()]
    if allowed and claims.get("aud") not in allowed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google sign-in failed: token was issued for a different app.",
        )

    return claims


async def authenticate_google_user(db: Session, id_token: str) -> TokenResponse:
    """Sign in (or sign up) a user with a Google ID token."""
    claims = await _verify_google_id_token(id_token)
    email = claims.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google sign-in failed: no email in token.",
        )

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()

    if user is None:
        user = User(
            name=claims.get("name") or email.split("@")[0],
            email=email,
            # Google users never log in with a password; store an unguessable one.
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            auth_provider="google",
            # Google already verified this address (checked above).
            email_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated.",
        )
    elif not user.email_verified:
        # A pending password signup just proved the address via Google.
        user.email_verified = True
        user.email_otp_hash = None
        user.email_otp_expires_at = None
        db.commit()

    token = create_access_token(data={"sub": str(user.id)})
    return TokenResponse(access_token=token)
