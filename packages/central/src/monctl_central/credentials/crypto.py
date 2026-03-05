"""AES-256-GCM encryption for credential storage.

Usage:
    from monctl_central.credentials.crypto import encrypt_secret, decrypt_secret

    encrypted = encrypt_secret('{"community": "public"}')
    plaintext = decrypt_secret(encrypted)

The encryption key is read from settings.encryption_key (MONCTL_ENCRYPTION_KEY env var).
It must be a 64-character hex string (32 bytes).

Generate a key with:
    python3 -c "import secrets; print(secrets.token_hex(32))"
"""

from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _get_key() -> bytes:
    """Return the 32-byte AES key from settings."""
    from monctl_central.config import settings

    key_hex = settings.encryption_key
    if not key_hex:
        raise RuntimeError(
            "MONCTL_ENCRYPTION_KEY is not set. "
            "Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
        )
    try:
        key_bytes = bytes.fromhex(key_hex)
    except ValueError as e:
        raise RuntimeError(f"MONCTL_ENCRYPTION_KEY must be a valid hex string: {e}") from e

    if len(key_bytes) != 32:
        raise RuntimeError(
            f"MONCTL_ENCRYPTION_KEY must be 64 hex characters (32 bytes), got {len(key_bytes)} bytes"
        )
    return key_bytes


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a plaintext string using AES-256-GCM.

    Returns a base64url-encoded string: base64(nonce + ciphertext + tag).
    The 12-byte nonce is randomly generated for each call.
    """
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit nonce as recommended for GCM
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    # Combine nonce + ciphertext (GCM tag is appended by cryptography library)
    combined = nonce + ciphertext
    return base64.urlsafe_b64encode(combined).decode("ascii")


def decrypt_secret(encrypted: str) -> str:
    """Decrypt a base64url-encoded AES-256-GCM ciphertext back to plaintext."""
    key = _get_key()
    aesgcm = AESGCM(key)
    combined = base64.urlsafe_b64decode(encrypted.encode("ascii"))
    nonce = combined[:12]
    ciphertext = combined[12:]
    plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext_bytes.decode("utf-8")


def encrypt_dict(data: dict) -> str:
    """Encrypt a dict as JSON."""
    return encrypt_secret(json.dumps(data))


def decrypt_dict(encrypted: str) -> dict:
    """Decrypt back to a dict."""
    return json.loads(decrypt_secret(encrypted))
