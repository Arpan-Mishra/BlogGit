"""
TDD tests for app/auth/encryption.py.

Write these BEFORE the implementation (RED phase).
Tests cover: round-trip, tampered ciphertext, wrong key, key rotation.
"""

import pytest
from cryptography.fernet import Fernet

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def kek() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture()
def alt_kek() -> str:
    return Fernet.generate_key().decode()


# ---------------------------------------------------------------------------
# encrypt_token / decrypt_token
# ---------------------------------------------------------------------------


def test_encrypt_returns_bytes(kek: str) -> None:
    from app.auth.encryption import encrypt_token

    result = encrypt_token("my-secret-token", kek)
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_encrypt_is_not_plaintext(kek: str) -> None:
    from app.auth.encryption import encrypt_token

    result = encrypt_token("my-secret-token", kek)
    assert b"my-secret-token" not in result


def test_round_trip(kek: str) -> None:
    from app.auth.encryption import decrypt_token, encrypt_token

    plaintext = "ghp_exampletoken1234"
    ciphertext = encrypt_token(plaintext, kek)
    assert decrypt_token(ciphertext, kek) == plaintext


def test_encrypt_same_value_produces_different_ciphertext(kek: str) -> None:
    """Fernet uses random IV — two encryptions of the same value must differ."""
    from app.auth.encryption import encrypt_token

    c1 = encrypt_token("token", kek)
    c2 = encrypt_token("token", kek)
    assert c1 != c2


def test_decrypt_with_wrong_key_raises(kek: str, alt_kek: str) -> None:
    from app.auth.encryption import EncryptionError, decrypt_token, encrypt_token

    ciphertext = encrypt_token("token", kek)
    with pytest.raises(EncryptionError):
        decrypt_token(ciphertext, alt_kek)


def test_decrypt_tampered_ciphertext_raises(kek: str) -> None:
    from app.auth.encryption import EncryptionError, decrypt_token, encrypt_token

    ciphertext = encrypt_token("token", kek)
    tampered = ciphertext[:-4] + b"xxxx"
    with pytest.raises(EncryptionError):
        decrypt_token(tampered, kek)


def test_decrypt_empty_bytes_raises(kek: str) -> None:
    from app.auth.encryption import EncryptionError, decrypt_token

    with pytest.raises(EncryptionError):
        decrypt_token(b"", kek)


# ---------------------------------------------------------------------------
# rotate_key
# ---------------------------------------------------------------------------


def test_rotate_key_produces_new_ciphertext(kek: str, alt_kek: str) -> None:
    from app.auth.encryption import encrypt_token, rotate_key

    ciphertext = encrypt_token("token", kek)
    rotated = rotate_key(ciphertext, old_kek=kek, new_kek=alt_kek)
    assert rotated != ciphertext


def test_rotate_key_decryptable_with_new_key(kek: str, alt_kek: str) -> None:
    from app.auth.encryption import decrypt_token, encrypt_token, rotate_key

    plaintext = "ghp_rotationtest"
    ciphertext = encrypt_token(plaintext, kek)
    rotated = rotate_key(ciphertext, old_kek=kek, new_kek=alt_kek)
    assert decrypt_token(rotated, alt_kek) == plaintext


def test_rotate_key_not_decryptable_with_old_key(kek: str, alt_kek: str) -> None:
    from app.auth.encryption import EncryptionError, decrypt_token, encrypt_token, rotate_key

    ciphertext = encrypt_token("token", kek)
    rotated = rotate_key(ciphertext, old_kek=kek, new_kek=alt_kek)
    with pytest.raises(EncryptionError):
        decrypt_token(rotated, kek)


# ---------------------------------------------------------------------------
# encrypt_token_or_none / decrypt_token_or_none (for nullable refresh tokens)
# ---------------------------------------------------------------------------


def test_encrypt_none_returns_none(kek: str) -> None:
    from app.auth.encryption import encrypt_token_or_none

    assert encrypt_token_or_none(None, kek) is None


def test_decrypt_none_returns_none(kek: str) -> None:
    from app.auth.encryption import decrypt_token_or_none

    assert decrypt_token_or_none(None, kek) is None


def test_encrypt_decrypt_none_safe(kek: str) -> None:
    from app.auth.encryption import decrypt_token_or_none, encrypt_token_or_none

    assert decrypt_token_or_none(encrypt_token_or_none("tok", kek), kek) == "tok"
