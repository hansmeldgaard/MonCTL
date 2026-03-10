"""Machine fingerprint — deterministic, stable across reboots.

SHA256(/etc/machine-id + ":" + primary-MAC)[:32] formatted as
XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX (groups of 4 hex chars).
"""

from __future__ import annotations

import hashlib
import uuid


def _get_machine_id() -> str:
    """Read /etc/machine-id (systemd) or fall back to hostname."""
    try:
        with open("/etc/machine-id") as f:
            return f.read().strip()
    except OSError:
        import socket
        return socket.gethostname()


def _get_primary_mac() -> str:
    """Get the MAC address of the first non-loopback interface."""
    mac = uuid.getnode()
    return ":".join(f"{(mac >> (8 * i)) & 0xff:02x}" for i in reversed(range(6)))


def generate_fingerprint() -> str:
    """Generate a deterministic machine fingerprint.

    Returns a 39-char string: XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX
    """
    machine_id = _get_machine_id()
    mac = _get_primary_mac()
    raw = hashlib.sha256(f"{machine_id}:{mac}".encode()).hexdigest()[:32]
    # Format as XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX
    return "-".join(raw[i:i + 4] for i in range(0, 32, 4))
