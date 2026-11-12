"""Authentication and user Pydantic schemas."""

import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class OTPRequestIn(BaseModel):
    """Schema for requesting a one-time password via email."""
    email: EmailStr = Field(..., description="User's work email address")


class OTPRequestResponse(BaseModel):
    """Response returned upon successful OTP dispatch."""
    message: str
    email: EmailStr
    expires_in_minutes: int


class OTPVerifyIn(BaseModel):
    """Schema for verifying a submitted OTP code."""
    email: EmailStr
    otp: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$", description="6-digit verification code")


class TokenOut(BaseModel):
    """Schema for JWT authentication tokens."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenIn(BaseModel):
    """Schema for refreshing expired access tokens."""
    refresh_token: str


class UserOut(BaseModel):
    """Public user profile schema."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None
    role: str
    is_active: bool
    created_at: datetime
