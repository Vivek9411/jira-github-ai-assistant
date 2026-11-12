"""Unit tests for AES-256 Token Vault encryption and decryption."""

import pytest
from app.core.vault import TokenVault, VaultDecryptionError, VaultEncryptionError


def test_token_vault_roundtrip() -> None:
    vault = TokenVault("DNNBZtNBVFFL9TkilQ0wXUmLnphKIzAVNXyR7k0r1fI=")
    original_secret = "ghp_mock_personal_access_token_12345"

    encrypted = vault.encrypt(original_secret)
    assert encrypted != original_secret
    assert isinstance(encrypted, str)

    decrypted = vault.decrypt(encrypted)
    assert decrypted == original_secret


def test_token_vault_empty_string_fails() -> None:
    vault = TokenVault("DNNBZtNBVFFL9TkilQ0wXUmLnphKIzAVNXyR7k0r1fI=")
    with pytest.raises(VaultEncryptionError):
        vault.encrypt("")

    with pytest.raises(VaultDecryptionError):
        vault.decrypt("")


def test_token_vault_invalid_ciphertext_fails() -> None:
    vault = TokenVault("DNNBZtNBVFFL9TkilQ0wXUmLnphKIzAVNXyR7k0r1fI=")
    with pytest.raises(VaultDecryptionError):
        vault.decrypt("corrupted_or_tampered_ciphertext")
