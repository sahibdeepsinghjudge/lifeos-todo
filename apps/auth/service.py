from __future__ import annotations

import secrets

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
from core.config import settings
from core.security import create_access_token, hash_password, verify_password


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
    return user


def authenticate_user(db: Session, data: LoginRequest) -> TokenResponse:
    user = db.execute(
        select(User).where(User.email == data.email)
    ).scalar_one_or_none()

    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The email or password you entered is incorrect. Please try again.",
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
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated.",
        )

    token = create_access_token(data={"sub": str(user.id)})
    return TokenResponse(access_token=token)
