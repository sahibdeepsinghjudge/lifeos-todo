from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleLoginRequest(BaseModel):
    id_token: str


class VerifyOtpRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)


class ResendOtpRequest(BaseModel):
    email: EmailStr


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    email: EmailStr | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    is_active: bool
    preferences: str | None = None
    auth_provider: str = "password"
    email_verified: bool = True
    subscription_status: str = "none"
    subscription_plan: str | None = None
    # Daily-use streak. While broken, streak_count still holds the frozen
    # previous streak (reset happens lazily on the next AI interaction).
    streak_count: int = 0
    streak_prev: int = 0
    streak_is_broken: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}

class UpdatePreferencesRequest(BaseModel):
    preferences: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)
