"""Unit tests for authentication security, OTP hashing, and JWT tokens."""

import pytest
from app.core.security import (
    TokenVerificationError,
    create_access_token,
    create_refresh_token,
    decode_jwt_token,
    generate_numeric_otp,
    hash_otp_with_salt,
    verify_salted_otp,
)


def test_numeric_otp_generation() -> None:
    otp = generate_numeric_otp(6)
    assert len(otp) == 6
    assert otp.isdigit()


def test_salted_otp_verification() -> None:
    otp = "482910"
    salt = "random_salt_hex_string"
    hashed = hash_otp_with_salt(otp, salt)

    assert verify_salted_otp("482910", salt, hashed) is True
    assert verify_salted_otp("123456", salt, hashed) is False


def test_jwt_token_roundtrip() -> None:
    subject = "user-12345"
    token = create_access_token(subject, extra_claims={"role": "PM"})

    payload = decode_jwt_token(token)
    assert payload["sub"] == subject
    assert payload["role"] == "PM"
    assert payload["type"] == "access"


def test_refresh_token_type() -> None:
    subject = "user-67890"
    token = create_refresh_token(subject)

    payload = decode_jwt_token(token)
    assert payload["sub"] == subject
    assert payload["type"] == "refresh"


def test_invalid_jwt_token_raises() -> None:
    with pytest.raises(TokenVerificationError):
        decode_jwt_token("invalid.jwt.token.string")
