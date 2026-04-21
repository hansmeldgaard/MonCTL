"""F-COL-026: PeerAuthServerInterceptor + PeerAuthClientInterceptor.

Tests the interceptors in isolation (no live gRPC). The server interceptor's
public contract: `intercept_service` either hands through to `continuation`
(good auth) or returns a method handler that aborts UNAUTHENTICATED. The
client interceptor's contract: stamp `authorization: Bearer <token>` into
every call's metadata.
"""

from __future__ import annotations

from collections import namedtuple
from typing import Any
from unittest.mock import AsyncMock

import pytest

from monctl_collector.peer.auth import (
    PeerAuthClientInterceptor,
    PeerAuthServerInterceptor,
    get_peer_token,
)


# ─── Test doubles ────────────────────────────────────────────────────────────


class _FakeCallDetails:
    def __init__(self, metadata: tuple[tuple[str, str], ...] = ()) -> None:
        self.invocation_metadata = metadata


_ClientCallDetails = namedtuple(
    "_ClientCallDetails",
    ["method", "timeout", "metadata", "credentials", "wait_for_ready"],
)


# ─── Server interceptor ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_server_accepts_matching_token():
    interceptor = PeerAuthServerInterceptor(token="secret-xyz")

    passed = {}

    async def continuation(details):
        passed["ok"] = True
        return "real-handler"  # sentinel — the real code is a gRPC handler

    details = _FakeCallDetails(metadata=(("authorization", "Bearer secret-xyz"),))
    result = await interceptor.intercept_service(continuation, details)

    assert passed.get("ok") is True
    assert result == "real-handler"


@pytest.mark.asyncio
async def test_server_accepts_token_without_bearer_prefix():
    """Some gRPC clients set a bare token — accept it for robustness."""
    interceptor = PeerAuthServerInterceptor(token="secret-xyz")

    async def continuation(details):
        return "real-handler"

    details = _FakeCallDetails(metadata=(("authorization", "secret-xyz"),))
    result = await interceptor.intercept_service(continuation, details)

    assert result == "real-handler"


@pytest.mark.asyncio
async def test_server_rejects_missing_metadata():
    interceptor = PeerAuthServerInterceptor(token="secret-xyz")

    async def continuation(details):
        pytest.fail("continuation must not run when auth is missing")

    details = _FakeCallDetails(metadata=())
    handler = await interceptor.intercept_service(continuation, details)

    # Exercise the deny handler — it calls context.abort(UNAUTHENTICATED,...)
    ctx = AsyncMock()
    await handler.unary_unary(request=None, context=ctx)
    ctx.abort.assert_awaited_once()
    code, message = ctx.abort.await_args.args
    # We don't import grpc here to keep the test independent — just check the
    # arg shape.
    assert "UNAUTHENTICATED" in repr(code)
    assert "F-COL-026" in message


@pytest.mark.asyncio
async def test_server_rejects_wrong_token():
    interceptor = PeerAuthServerInterceptor(token="secret-xyz")

    async def continuation(details):
        pytest.fail("continuation must not run with a wrong token")

    details = _FakeCallDetails(metadata=(("authorization", "Bearer other-token"),))
    handler = await interceptor.intercept_service(continuation, details)

    ctx = AsyncMock()
    await handler.unary_unary(request=None, context=ctx)
    ctx.abort.assert_awaited_once()


def test_server_rejects_empty_token_init():
    with pytest.raises(ValueError):
        PeerAuthServerInterceptor(token="")


# ─── Client interceptor ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_injects_authorization_metadata():
    interceptor = PeerAuthClientInterceptor(token="secret-xyz")

    details = _ClientCallDetails(
        method="/x",
        timeout=None,
        metadata=None,
        credentials=None,
        wait_for_ready=None,
    )

    captured: dict[str, Any] = {}

    async def continuation(updated_details, request):
        captured["metadata"] = list(updated_details.metadata or [])
        return "ok"

    out = await interceptor.intercept_unary_unary(
        continuation, details, request=object()
    )

    assert out == "ok"
    assert ("authorization", "Bearer secret-xyz") in captured["metadata"]


@pytest.mark.asyncio
async def test_client_preserves_existing_metadata():
    interceptor = PeerAuthClientInterceptor(token="secret-xyz")

    details = _ClientCallDetails(
        method="/x",
        timeout=None,
        metadata=[("x-trace-id", "t-123")],
        credentials=None,
        wait_for_ready=None,
    )

    captured: dict[str, Any] = {}

    async def continuation(updated_details, request):
        captured["metadata"] = list(updated_details.metadata or [])
        return "ok"

    await interceptor.intercept_unary_unary(continuation, details, request=object())

    md = captured["metadata"]
    assert ("x-trace-id", "t-123") in md
    assert ("authorization", "Bearer secret-xyz") in md


def test_client_rejects_empty_token_init():
    with pytest.raises(ValueError):
        PeerAuthClientInterceptor(token="")


# ─── Token source ────────────────────────────────────────────────────────────


def test_get_peer_token_empty_when_unset(monkeypatch):
    monkeypatch.delenv("MONCTL_PEER_TOKEN", raising=False)
    assert get_peer_token() == ""


def test_get_peer_token_reads_env(monkeypatch):
    monkeypatch.setenv("MONCTL_PEER_TOKEN", "abc-123")
    assert get_peer_token() == "abc-123"
