"""Token Vault module for AES-256 symmetric encryption of integration tokens."""

import logging
from cryptography.fernet import Fernet, InvalidToken
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class VaultError(Exception):
    """Base exception for Vault encryption/decryption failures."""
    pass


class VaultEncryptionError(VaultError):
    """Raised when token encryption fails."""
    pass


class VaultDecryptionError(VaultError):
    """Raised when token decryption fails."""
    pass


class TokenVault:
    """Provides secure encryption and decryption of third-party credentials at rest.
    
    Uses Fernet symmetric authenticated encryption (AES-128-CBC + HMAC-SHA256).
    """

    def __init__(self, key: str | None = None) -> None:
        encryption_key = key or get_settings().ENCRYPTION_KEY
        try:
            self._fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
        except Exception as exc:
            raise VaultError("Invalid Fernet master key configured") from exc

    def encrypt(self, secret_text: str) -> str:
        """Encrypt plaintext secret into an ASCII ciphertext string."""
        if not secret_text:
            raise VaultEncryptionError("Cannot encrypt an empty secret")
        try:
            encrypted_bytes = self._fernet.encrypt(secret_text.encode("utf-8"))
            return encrypted_bytes.decode("utf-8")
        except Exception as exc:
            logger.error("Failed to encrypt token: %s", type(exc).__name__)
            raise VaultEncryptionError("Token encryption failed") from exc

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt ASCII ciphertext back into the original plaintext secret."""
        if not ciphertext:
            raise VaultDecryptionError("Cannot decrypt an empty ciphertext")
        try:
            decrypted_bytes = self._fernet.decrypt(ciphertext.encode("utf-8"))
            return decrypted_bytes.decode("utf-8")
        except InvalidToken as exc:
            logger.error("Invalid token or corrupted ciphertext during decryption")
            raise VaultDecryptionError("Token decryption failed: invalid ciphertext or corrupted key") from exc
        except Exception as exc:
            logger.error("Unexpected error during token decryption: %s", type(exc).__name__)
            raise VaultDecryptionError("Token decryption failed") from exc


# Global vault instance for dependency injection
default_token_vault = TokenVault()
