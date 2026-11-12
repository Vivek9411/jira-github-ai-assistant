"""Security module for JWT token management and OTP hashing."""

import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
import jwt
from passlib.context import CryptContext
from app.core.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
settings = get_settings()


class SecurityError(Exception):
    """Base exception for security and authentication errors."""
    pass


class TokenVerificationError(SecurityError):
    """Raised when JWT verification fails."""
    pass


def generate_numeric_otp(length: int = 6) -> str:
    """Generate a cryptographically secure numeric OTP string."""
    digits = [str(secrets.randbelow(10)) for _ in range(length)]
    return "".join(digits)


def hash_otp_with_salt(otp: str, salt: str) -> str:
    """Hash OTP combined with salt using SHA-256 for fast, tamper-proof verification."""
    combined = f"{otp}:{salt}".encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def verify_salted_otp(plain_otp: str, salt: str, hashed_otp: str) -> bool:
    """Compare plain OTP against hashed OTP in constant time."""
    expected_hash = hash_otp_with_salt(plain_otp, salt)
    return secrets.compare_digest(expected_hash, hashed_otp)


def create_access_token(subject: str, extra_claims: dict[str, Any] | None = None) -> str:
    """Generate signed JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode: dict[str, Any] = {
        "sub": subject,
        "exp": expire,
        "type": "access",
    }
    if extra_claims:
        to_encode.update(extra_claims)
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: str) -> str:
    """Generate signed JWT refresh token."""
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode: dict[str, Any] = {
        "sub": subject,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_jwt_token(token: str) -> dict[str, Any]:
    """Decode and validate JWT token claims."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError as exc:
        raise TokenVerificationError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenVerificationError("Invalid authentication token") from exc
