"""Shared input validators for MonCTL."""

from __future__ import annotations

import re
import uuid
from ipaddress import IPv4Address, IPv6Address

# ── Constants ────────────────────────────────────────────────────────────────

MAX_NAME_LENGTH = 255
MAX_SHORT_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 2000
MAX_LABEL_KEY_LENGTH = 64
MAX_LABEL_VALUE_LENGTH = 255
MAX_METADATA_KEYS = 50

# ── Regex Patterns ───────────────────────────────────────────────────────────

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,126}[a-z0-9]$")
LABEL_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}[a-z0-9]$")
OID_RE = re.compile(r"^(\d+\.){2,}\d+$")
SEMVER_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
HOSTNAME_RE = re.compile(
    r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z0-9-]{1,63})*$"
)
ALERT_WINDOW_RE = re.compile(r"^\d+[smh]$")


# ── Validator Functions ──────────────────────────────────────────────────────

def validate_uuid(value: str, field_name: str = "id") -> uuid.UUID:
    """Parse and return a UUID, raise ValueError with field name on failure."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid UUID for {field_name}: '{value}'")


def validate_address(value: str) -> str:
    """Validate a device address: IPv4, IPv6, hostname, or URL."""
    value = value.strip()
    if not value:
        raise ValueError("Address cannot be empty")
    if len(value) > 500:
        raise ValueError("Address too long (max 500 characters)")

    try:
        IPv4Address(value)
        return value
    except ValueError:
        pass

    try:
        IPv6Address(value)
        return value
    except ValueError:
        pass

    if HOSTNAME_RE.match(value):
        return value

    if value.startswith(("http://", "https://")):
        return value

    raise ValueError(
        f"Invalid address: '{value}'. Must be an IPv4/IPv6 address, hostname, or URL"
    )


def validate_labels(labels: dict[str, str]) -> dict[str, str]:
    """Validate a labels dict: keys and values are constrained strings."""
    if len(labels) > MAX_METADATA_KEYS:
        raise ValueError(f"Too many labels (max {MAX_METADATA_KEYS})")

    validated = {}
    for key, val in labels.items():
        key = key.strip().lower()
        if not LABEL_KEY_RE.match(key):
            raise ValueError(
                f"Invalid label key '{key}': must be 2-64 chars, lowercase, "
                "start with letter, contain only a-z, 0-9, hyphens, underscores"
            )
        val = str(val).strip()
        if len(val) > MAX_LABEL_VALUE_LENGTH:
            raise ValueError(
                f"Label value for '{key}' too long (max {MAX_LABEL_VALUE_LENGTH})"
            )
        validated[key] = val
    return validated


def validate_metadata(metadata: dict) -> dict:
    """Validate a metadata dict: limit key count."""
    if len(metadata) > MAX_METADATA_KEYS:
        raise ValueError(f"Too many metadata keys (max {MAX_METADATA_KEYS})")
    return metadata


def validate_oid(value: str) -> str:
    """Validate an SNMP OID string."""
    value = value.strip()
    if not OID_RE.match(value):
        raise ValueError(
            f"Invalid OID '{value}': must be dotted numeric (e.g. 1.3.6.1.2.1.1.1.0)"
        )
    return value


def validate_semver(value: str) -> str:
    """Validate a semver string (1.0 or 1.0.0)."""
    value = value.strip()
    if not SEMVER_RE.match(value):
        raise ValueError(f"Invalid version '{value}': must be semver (e.g. 1.0.0)")
    return value


def validate_hex_color(value: str) -> str:
    """Validate a hex color string (#RRGGBB)."""
    value = value.strip()
    if not HEX_COLOR_RE.match(value):
        raise ValueError(f"Invalid color '{value}': must be hex #RRGGBB")
    return value


def validate_alert_window(value: str) -> str:
    """Validate an alert window string (e.g. 5m, 1h, 30s)."""
    value = value.strip()
    if not ALERT_WINDOW_RE.match(value):
        raise ValueError(f"Invalid window '{value}': must be like 5m, 1h, 30s")
    return value


def validate_slug(value: str, field_name: str = "slug") -> str:
    """Validate a slug string."""
    value = value.strip()
    if not SLUG_RE.match(value):
        raise ValueError(
            f"Invalid {field_name}: must be 2-128 chars, lowercase alphanumeric + hyphens"
        )
    return value
