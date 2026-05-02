"""Field diffing and sensitive value redaction for audit rows."""

from __future__ import annotations

import datetime as _dt
import json
import uuid
from typing import Any

# Field-name substrings that trigger redaction. Matched case-insensitively.
_SENSITIVE_KEYS = (
    "password",
    "password_hash",
    "api_key",
    # `api_keys` table stores `key_hash` (SHA-256 of the bearer key).
    # The hash is one-way but defence-in-depth says don't ship it through
    # the audit pipeline either — a leaked hash is still useful to an
    # attacker for time-correlation / rainbow-table attempts on short keys.
    # Listed before "secret" so substring matching catches it on the
    # `api_keys` row that S-CEN-018 newly audits.
    "key_hash",
    "encryption_key",
    "jwt_secret",
    "credential_value",
    "secret",
    "token",
    "private_key",
)

_MAX_VALUE_STR = 8192  # max length of any single JSON-encoded value


def _is_sensitive(field_name: str) -> bool:
    lower = field_name.lower()
    return any(k in lower for k in _SENSITIVE_KEYS)


def _coerce(value: Any) -> Any:
    """Convert non-JSON types to JSON-serializable equivalents."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return f"<bytes:{len(value)}>"
    if isinstance(value, dict):
        return redact_dict(value)
    if isinstance(value, (list, tuple)):
        return [_coerce(v) for v in value]
    return value


def redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of data with sensitive fields replaced by '***'."""
    out: dict[str, Any] = {}
    for k, v in data.items():
        if _is_sensitive(k):
            out[k] = "***"
        else:
            out[k] = _coerce(v)
    return out


def to_json(data: dict[str, Any]) -> str:
    """Serialize a dict to JSON, redacting sensitive fields and capping size."""
    try:
        text = json.dumps(redact_dict(data), ensure_ascii=False, default=str)
    except Exception:
        return "{}"
    if len(text) > _MAX_VALUE_STR:
        text = text[:_MAX_VALUE_STR] + '..."(truncated)"'
    return text


def diff_fields(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Return the list of field names whose values changed."""
    changed: list[str] = []
    keys = set(old.keys()) | set(new.keys())
    for k in keys:
        if old.get(k) != new.get(k):
            changed.append(k)
    return sorted(changed)
