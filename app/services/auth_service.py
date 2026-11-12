"""Authentication business logic service."""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_jwt_token,
    generate_numeric_otp,
    hash_otp_with_salt,
    verify_salted_otp,
)
from app.models.user import OTPRequest, User
from app.schemas.auth import TokenOut
from app.services.email_service import email_service

logger = logging.getLogger(__name__)
settings = get_settings()


class AuthServiceError(Exception):
    """Base exception for authentication service errors."""
    pass


class InvalidCredentialsError(AuthServiceError):
    """Raised when OTP or credentials are invalid."""
    pass


class OTPExpiredError(AuthServiceError):
    """Raised when submitted OTP has expired."""
    pass


class MaxAttemptsExceededError(AuthServiceError):
    """Raised when maximum OTP verification attempts are exceeded."""
    pass


class UserNotFoundError(AuthServiceError):
    """Raised when user account is not found."""
    pass


class AuthService:
    """Manages passwordless OTP authentication and JWT issuance."""

    async def get_or_create_user(self, session: AsyncSession, email: str, full_name: str | None = None) -> User:
        """Retrieve existing user by email or create a new user profile."""
        query = select(User).where(User.email == email.lower().strip())
        result = await session.execute(query)
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                email=email.lower().strip(),
                full_name=full_name,
                role="Developer",
                is_active=True,
            )
            session.add(user)
            await session.flush()
            logger.info("Created new user account for %s", user.email)

        return user

    async def request_otp(self, session: AsyncSession, email: str) -> None:
        """Generate, store, and dispatch a new OTP verification code for the user."""
        user = await self.get_or_create_user(session, email)

        # Invalidate previous unused OTP requests for this user
        await session.execute(
            update(OTPRequest)
            .where(OTPRequest.user_id == user.id, OTPRequest.is_used.is_(False))
            .values(is_used=True)
        )

        plain_otp = generate_numeric_otp(length=6)
        salt = secrets.token_hex(16)
        hashed_otp = hash_otp_with_salt(plain_otp, salt)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)

        otp_record = OTPRequest(
            user_id=user.id,
            hashed_otp=hashed_otp,
            salt=salt,
            expires_at=expires_at,
            is_used=False,
            attempts=0,
        )
        session.add(otp_record)
        await session.commit()

        # Dispatch OTP to user
        await email_service.send_otp_email(user.email, plain_otp)

    async def verify_otp(self, session: AsyncSession, email: str, plain_otp: str) -> tuple[User, TokenOut]:
        """Validate submitted OTP and return user with access & refresh tokens."""
        user_query = select(User).where(User.email == email.lower().strip())
        user_result = await session.execute(user_query)
        user = user_result.scalar_one_or_none()

        if not user:
            raise UserNotFoundError("User account does not exist")

        otp_query = (
            select(OTPRequest)
            .where(OTPRequest.user_id == user.id, OTPRequest.is_used.is_(False))
            .order_by(OTPRequest.created_at.desc())
            .limit(1)
        )
        otp_result = await session.execute(otp_query)
        otp_record = otp_result.scalar_one_or_none()

        if not otp_record:
            raise InvalidCredentialsError("No pending verification request found")

        if otp_record.attempts >= settings.OTP_MAX_ATTEMPTS:
            otp_record.is_used = True
            await session.commit()
            raise MaxAttemptsExceededError("Maximum verification attempts exceeded. Please request a new code.")

        if otp_record.is_expired:
            otp_record.is_used = True
            await session.commit()
            raise OTPExpiredError("Verification code has expired. Please request a new code.")

        is_valid = verify_salted_otp(plain_otp, otp_record.salt, otp_record.hashed_otp)
        if not is_valid:
            otp_record.attempts += 1
            await session.commit()
            raise InvalidCredentialsError("Invalid verification code")

        # Code is valid; consume it
        otp_record.is_used = True
        await session.commit()

        access_token = create_access_token(
            subject=str(user.id),
            extra_claims={"email": user.email, "role": user.role},
        )
        refresh_token = create_refresh_token(subject=str(user.id))

        tokens = TokenOut(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
        return user, tokens

    async def refresh_access_token(self, session: AsyncSession, refresh_token_str: str) -> TokenOut:
        """Validate refresh token and issue a fresh access token."""
        payload = decode_jwt_token(refresh_token_str)
        if payload.get("type") != "refresh":
            raise InvalidCredentialsError("Invalid token type")

        user_id_str = payload.get("sub")
        if not user_id_str:
            raise InvalidCredentialsError("Malformed token subject")

        query = select(User).where(User.id == user_id_str, User.is_active.is_(True))
        result = await session.execute(query)
        user = result.scalar_one_or_none()

        if not user:
            raise UserNotFoundError("User account not found or inactive")

        new_access_token = create_access_token(
            subject=str(user.id),
            extra_claims={"email": user.email, "role": user.role},
        )
        new_refresh_token = create_refresh_token(subject=str(user.id))

        return TokenOut(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )


auth_service = AuthService()
