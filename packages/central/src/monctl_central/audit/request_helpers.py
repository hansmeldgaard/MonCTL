"""Helpers for extracting client context from requests behind HAProxy."""

from __future__ import annotations

import ipaddress

from starlette.requests import Request


def _trusted_proxy_set() -> frozenset[str]:
    """Parse ``settings.trusted_proxies`` into a normalised IP-string set.

    Reading from settings on each call (vs. caching) keeps this safe for
    test setups that monkeypatch the value mid-process. Cost is one
    string split per audit row, which is well under the audit-buffer
    cap.
    """
    from monctl_central.config import settings

    raw = (getattr(settings, "trusted_proxies", "") or "").strip()
    out: set[str] = set()
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            out.add(str(ipaddress.ip_address(entry)))
        except ValueError:
            # Silently skip junk; a misconfigured value mustn't break
            # the audit pipeline. The behaviour is fail-closed (no XFF
            # trust) which is the safe default for an unparseable list.
            continue
    return frozenset(out)


def _peer_is_trusted_proxy(request: Request) -> bool:
    """True if the immediate connection peer is one of the trusted proxies.

    HAProxy / Nginx / etc. sit between the operator's browser and central
    and rewrite ``X-Forwarded-For``. We only trust XFF when the immediate
    peer (request.client.host) is a known proxy — otherwise an attacker
    can spoof their source IP for every audit row by sending
    ``X-Forwarded-For: 10.0.0.1`` directly.
    """
    if request.client is None:
        return False
    try:
        peer = str(ipaddress.ip_address(request.client.host))
    except (ValueError, TypeError):
        return False
    return peer in _trusted_proxy_set()


def get_client_ip(request: Request) -> str:
    """Return the real client IP, honoring X-Forwarded-For when present.

    S-CEN-009 — XFF / X-Real-IP are trusted ONLY when the immediate
    connection peer is in ``settings.trusted_proxies``. Single-node
    customer installs that expose port 8443 directly are no longer
    XFF-spoofable.
    """
    if _peer_is_trusted_proxy(request):
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # First IP in the list is the original client
            return xff.split(",")[0].strip()
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()
    if request.client:
        return request.client.host
    return ""


def get_user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")
