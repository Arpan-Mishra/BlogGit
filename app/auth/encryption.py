"""
Fernet-based symmetric encryption for OAuth token storage.

All OAuth tokens are encrypted before writing to Postgres and decrypted
on read. The key-encryption key (KEK) lives in an environment variable and
is never stored in the database.

Usage:
    ciphertext = encrypt_token(plaintext, settings.blog_copilot_kek.get_secret_value())
    plaintext  = decrypt_token(ciphertext, settings.blog_copilot_kek.get_secret_value())

Key rotation:
    new_cipher = rotate_key(old_cipher, old_kek=old, new_kek=new)
"""

from cryptography.fernet import Fernet, InvalidToken


class EncryptionError(Exception):
    """Raised when decryption fails (wrong key, tampered ciphertext, etc.)."""


def encrypt_token(plaintext: str, kek: str) -> bytes:
    """Encrypt *plaintext* with *kek* and return Fernet ciphertext bytes."""
    f = Fernet(kek.encode() if isinstance(kek, str) else kek)
    return f.encrypt(plaintext.encode())


def decrypt_token(ciphertext: bytes, kek: str) -> str:
    """Decrypt *ciphertext* with *kek* and return plaintext string.

    Raises:
        EncryptionError: if the key is wrong, the token is expired,
                         or the ciphertext has been tampered with.
    """
    if not ciphertext:
        raise EncryptionError("Cannot decrypt empty ciphertext")
    try:
        f = Fernet(kek.encode() if isinstance(kek, str) else kek)
        return f.decrypt(ciphertext).decode()
    except (InvalidToken, Exception) as exc:
        raise EncryptionError("Decryption failed") from exc


def rotate_key(ciphertext: bytes, *, old_kek: str, new_kek: str) -> bytes:
    """Re-encrypt *ciphertext* from *old_kek* to *new_kek*.

    Use this during key rotation to migrate all stored tokens without
    ever having plaintext tokens in application memory longer than needed.
    """
    plaintext = decrypt_token(ciphertext, old_kek)
    return encrypt_token(plaintext, new_kek)


def encrypt_token_or_none(plaintext: str | None, kek: str) -> bytes | None:
    """Encrypt *plaintext* if not None, otherwise return None.

    Convenience wrapper for nullable fields (e.g. refresh_token).
    """
    if plaintext is None:
        return None
    return encrypt_token(plaintext, kek)


def decrypt_token_or_none(ciphertext: bytes | None, kek: str) -> str | None:
    """Decrypt *ciphertext* if not None, otherwise return None."""
    if ciphertext is None:
        return None
    return decrypt_token(ciphertext, kek)
