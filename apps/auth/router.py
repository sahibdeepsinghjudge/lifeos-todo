from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from apps.auth.models import User
from apps.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
    UpdatePreferencesRequest,
)
from apps.auth.service import (
    authenticate_user,
    change_password,
    deactivate_user,
    register_user,
)
from core.database import get_db
from core.security import get_current_user

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    user = register_user(db, data)
    return user


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    return authenticate_user(db, data)


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me/password")
def update_password(
    data: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    change_password(db, current_user, data)
    return {"detail": "Password updated"}


@router.delete("/me")
def delete_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deactivate_user(db, current_user)
    return {"detail": "Account deactivated"}


@router.put("/me/preferences", response_model=UserResponse)
def update_preferences(
    data: UpdatePreferencesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.preferences = data.preferences
    db.commit()
    db.refresh(current_user)
    return current_user
