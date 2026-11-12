"""Authentication endpoints for passwordless email OTP and JWT lifecycle."""

from fastapi import APIRouter, HTTPException, status
from app.api.deps import CurrentUserDep, SessionDep
from app.core.config import get_settings
from app.schemas.auth import (
    OTPRequestIn,
    OTPRequestResponse,
    OTPVerifyIn,
    RefreshTokenIn,
    TokenOut,
    UserOut,
)
from app.services.auth_service import (
    InvalidCredentialsError,
    MaxAttemptsExceededError,
    OTPExpiredError,
    UserNotFoundError,
    auth_service,
)
from app.services.email_service import EmailDeliveryError

router = APIRouter(prefix="/auth", tags=["Authentication"])
settings = get_settings()


@router.post(
    "/otp/request",
    response_model=OTPRequestResponse,
    status_code=status.HTTP_200_OK,
    summary="Request Email OTP",
    description="Generate and deliver a 6-digit verification code to the specified email address.",
)
async def request_otp(
    payload: OTPRequestIn,
    session: SessionDep,
) -> OTPRequestResponse:
    try:
        await auth_service.request_otp(session, payload.email)
        return OTPRequestResponse(
            message="Verification code dispatched successfully",
            email=payload.email,
            expires_in_minutes=settings.OTP_EXPIRE_MINUTES,
        )
    except EmailDeliveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to deliver verification email. Please try again later.",
        ) from exc


@router.post(
    "/otp/verify",
    response_model=TokenOut,
    status_code=status.HTTP_200_OK,
    summary="Verify OTP & Login",
    description="Validate 6-digit code and receive access and refresh JWT tokens.",
)
async def verify_otp(
    payload: OTPVerifyIn,
    session: SessionDep,
) -> TokenOut:
    try:
        _, tokens = await auth_service.verify_otp(session, payload.email, payload.otp)
        return tokens
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except OTPExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=str(exc),
        ) from exc
    except MaxAttemptsExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/refresh",
    response_model=TokenOut,
    status_code=status.HTTP_200_OK,
    summary="Refresh Access Token",
    description="Issue a new JWT access token using a valid refresh token.",
)
async def refresh_token(
    payload: RefreshTokenIn,
    session: SessionDep,
) -> TokenOut:
    try:
        return await auth_service.refresh_access_token(session, payload.refresh_token)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/me",
    response_model=UserOut,
    status_code=status.HTTP_200_OK,
    summary="Get Current User Profile",
    description="Retrieve the authenticated user's profile details.",
)
async def get_current_user_profile(
    current_user: CurrentUserDep,
) -> UserOut:
    return UserOut.model_validate(current_user)
