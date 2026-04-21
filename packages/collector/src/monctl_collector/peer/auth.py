"""F-COL-026: shared-secret auth for the cache-node ↔ poll-worker gRPC channel.

The peer channel runs over a Docker bridge network inside the collector host.
Anything else running in that network namespace (e.g. a misbehaving app running
inside a poll-worker, a sidecar that got too much access) can speak to the
cache-node's gRPC port without this gate — and the cache-node happily serves
credentials over it via `GetCredential`.

A bearer token shared between the local cache-node, poll-worker and any other
legitimate peer client is enough to close the intra-network-namespace gap.
Configured via `MONCTL_PEER_TOKEN`. When unset, the server stays in
"grandfathered" mode (no enforcement, warns once on startup) so the code can
land before every host has been re-provisioned with the env var.
"""

from __future__ import annotations

import hmac
import os

import grpc
import structlog

_PEER_TOKEN_ENV = "MONCTL_PEER_TOKEN"
_AUTH_METADATA_KEY = "authorization"

logger = structlog.get_logger()


def get_peer_token() -> str:
    """Return the configured peer token, or empty string if unset."""
    return os.environ.get(_PEER_TOKEN_ENV, "") or ""


# ─── Server side ─────────────────────────────────────────────────────────────


class PeerAuthServerInterceptor(grpc.aio.ServerInterceptor):
    """Reject any RPC that doesn't carry a matching bearer token.

    Expected metadata: `authorization: Bearer <token>`. The compare is
    constant-time (`hmac.compare_digest`) so a timing side-channel can't
    be used to recover the token byte-by-byte.
    """

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("PeerAuthServerInterceptor requires a non-empty token")
        self._token = token

    async def intercept_service(self, continuation, handler_call_details):
        metadata = dict(handler_call_details.invocation_metadata or ())
        raw = metadata.get(_AUTH_METADATA_KEY, "")
        # Accept with or without the "Bearer " prefix so grpc clients that
        # happen to set plain "authorization: <token>" still work.
        presented = raw.removeprefix("Bearer ").strip()
        if not presented or not hmac.compare_digest(presented, self._token):
            return _deny()
        return await continuation(handler_call_details)


def _deny() -> grpc.RpcMethodHandler:
    """Build a handler that short-circuits the RPC with UNAUTHENTICATED."""

    async def _abort(request, context):
        await context.abort(
            grpc.StatusCode.UNAUTHENTICATED,
            "peer authentication required (F-COL-026)",
        )

    return grpc.unary_unary_rpc_method_handler(_abort)


# ─── Client side ─────────────────────────────────────────────────────────────


class PeerAuthClientInterceptor(
    grpc.aio.UnaryUnaryClientInterceptor,
    grpc.aio.UnaryStreamClientInterceptor,
    grpc.aio.StreamUnaryClientInterceptor,
    grpc.aio.StreamStreamClientInterceptor,
):
    """Attach `authorization: Bearer <token>` metadata to every outbound RPC."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("PeerAuthClientInterceptor requires a non-empty token")
        self._header = ("authorization", f"Bearer {token}")

    def _augment(self, client_call_details: grpc.aio.ClientCallDetails) -> grpc.aio.ClientCallDetails:
        md = list(client_call_details.metadata or [])
        md.append(self._header)
        # ClientCallDetails is a NamedTuple; rebuild with updated metadata.
        return client_call_details._replace(metadata=md)

    async def intercept_unary_unary(self, continuation, client_call_details, request):
        return await continuation(self._augment(client_call_details), request)

    async def intercept_unary_stream(self, continuation, client_call_details, request):
        return await continuation(self._augment(client_call_details), request)

    async def intercept_stream_unary(self, continuation, client_call_details, request_iterator):
        return await continuation(self._augment(client_call_details), request_iterator)

    async def intercept_stream_stream(self, continuation, client_call_details, request_iterator):
        return await continuation(self._augment(client_call_details), request_iterator)
