"""Helpers for extracting client context from requests behind HAProxy."""

from __future__ import annotations

from starlette.requests import Request


def get_client_ip(request: Request) -> str:
    """Return the real client IP, honoring X-Forwarded-For when present."""
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
