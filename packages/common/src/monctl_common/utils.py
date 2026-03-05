"""Shared utility functions."""

from __future__ import annotations

import hashlib
import secrets
import string
from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


def generate_api_key(prefix: str) -> str:
    """Generate a random API key with the given prefix.

    Format: {prefix}{32 random alphanumeric chars}
    Example: monctl_c_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
    """
    chars = string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(32))
    return f"{prefix}{random_part}"


def hash_api_key(key: str) -> str:
    """Hash an API key using SHA-256 for storage."""
    return hashlib.sha256(key.encode()).hexdigest()


def key_prefix_display(key: str) -> str:
    """Extract the display prefix from an API key (prefix + first 8 chars of random part).

    Example: monctl_c_a1b2c3d4 (for identification without exposing the full key)
    """
    # Find the last underscore to split prefix from random part
    parts = key.rsplit("_", 1)
    if len(parts) == 2:
        prefix_part = key[: len(key) - len(parts[1])]
        return f"{prefix_part}{parts[1][:8]}"
    return key[:20]


def hash_assignment_to_ring(assignment_id: str) -> int:
    """Hash an assignment ID to a position on the consistent hash ring.

    Returns an integer in [0, 2^32).
    """
    digest = hashlib.md5(assignment_id.encode()).hexdigest()  # noqa: S324 - MD5 used for distribution, not security
    return int(digest[:8], 16)
