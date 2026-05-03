"""Tests for the OAuth2 / OIDC provider in ``monctl_central.auth.oauth``.

Closes T-CEN-010 from review #2: the 511-line provider shipped for
Superset SSO with **zero tests**. Critical paths covered here:

  * authorize-endpoint redirect-URI exact-match (the main defence
    against open-redirect / token-theft)
  * authorize-endpoint redirects unauthenticated users to /login
    with the original URL preserved as ?next= (open-redirect-safe)
  * superset_access='none' denies via redirect with error param
  * /token enforces HTTP Basic auth with constant-time secret compare
  * /token authorization_code grant: code is single-use, redirect_uri
    must match the one used on /authorize, returns access + refresh
    + id_token
  * /userinfo Bearer auth + claims envelope (preferred_username,
    superset_access, all_tenants, tenant_ids)
  * OIDC discovery endpoint shape

Tests build on the existing ``client`` and ``auth_client`` fixtures
from ``conftest.py`` (FastAPI ASGI transport + SQLite session +
mocked Redis). The mock_redis fixture is replaced with a simple
in-memory KV stub so ``_store_code`` / ``_consume_code`` actually
round-trip — the OAuth flow doesn't make sense without it.
"""

from __future__ import annotations

import base64
import json
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient

from monctl_central.config import settings


# ---------------------------------------------------------------------------
# OAuth-specific fixtures
# ---------------------------------------------------------------------------


_TEST_CLIENT_ID = "test-client"
_TEST_CLIENT_SECRET = "test-secret-very-long-and-random"
_TEST_REDIRECT = "https://app.example.com/oauth-callback"


@pytest.fixture(autouse=True)
def configure_oauth(monkeypatch):
    """Configure central as an OAuth2 provider for every test in this file.

    The default `settings` has empty oauth_client_id / _secret /
    redirect_uris, which makes every endpoint return 503 unconfigured.
    Set sane test values (long enough to satisfy any secret-length
    rules) and a single allowed redirect_uri.
    """
    monkeypatch.setattr(settings, "oauth_client_id", _TEST_CLIENT_ID)
    monkeypatch.setattr(settings, "oauth_client_secret", _TEST_CLIENT_SECRET)
    monkeypatch.setattr(
        settings, "oauth_redirect_uris", _TEST_REDIRECT
    )
    monkeypatch.setattr(settings, "oauth_issuer", "https://test.example")


class _RedisKVStub:
    """Tiny in-memory KV that satisfies the OAuth code store/consume calls.

    Implements the four async methods OAuth touches:
      * ``setex(key, ttl, value)`` — store
      * ``execute_command("GETDEL", key)`` — atomic fetch+delete
      * ``get(key)`` / ``delete(key)`` — fallback path

    The default ``mock_redis`` fixture in conftest is an AsyncMock that
    returns MagicMock objects, which doesn't round-trip the JSON payload
    OAuth needs to unmarshal. This stub gives the same protocol surface
    with real KV behaviour so the full code → token round-trip works.
    """

    def __init__(self) -> None:
        self._kv: dict[str, bytes] = {}

    async def setex(self, key: str, ttl: int, value) -> bool:  # noqa: ARG002
        self._kv[key] = value.encode() if isinstance(value, str) else bytes(value)
        return True

    async def execute_command(self, *args):
        # OAuth only calls this with ("GETDEL", key).
        if len(args) >= 2 and str(args[0]).upper() == "GETDEL":
            return self._kv.pop(args[1], None)
        return None

    async def get(self, key: str):
        return self._kv.get(key)

    async def delete(self, key: str) -> int:
        return 1 if self._kv.pop(key, None) is not None else 0

    # Methods the rest of central touches via `_redis` — keep them tolerant
    # so OAuth tests that hit other code paths (cache reads, login throttle)
    # don't blow up.
    async def incr(self, key: str) -> int:
        return 0

    async def expire(self, key: str, ttl: int) -> bool:  # noqa: ARG002
        return True

    async def exists(self, key: str) -> int:
        return 0

    async def hincrby(self, key: str, field: str, amount: int = 1) -> int:  # noqa: ARG002
        return 0

    async def hget(self, key: str, field: str):  # noqa: ARG002
        return None

    async def hgetall(self, key: str):  # noqa: ARG002
        return {}

    async def set(self, key: str, value, **kwargs) -> bool:  # noqa: ARG002
        self._kv[key] = value.encode() if isinstance(value, str) else bytes(value)
        return True


@pytest.fixture
def kv_redis():
    """In-memory stub matching the Redis surface OAuth uses."""
    return _RedisKVStub()


@pytest.fixture
async def oauth_client(client: AsyncClient, kv_redis) -> AsyncClient:
    """``client`` with the kv-redis stub swapped in for the conftest mock."""
    from monctl_central import cache

    cache._redis = kv_redis
    return client


@pytest.fixture
async def authed_oauth_client(
    oauth_client: AsyncClient, admin_credentials: dict
) -> AsyncClient:
    """Logged-in admin ready to drive the authorize flow."""
    resp = await oauth_client.post("/v1/auth/login", json=admin_credentials)
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    for k, v in resp.cookies.items():
        oauth_client.cookies.set(k, v)
    return oauth_client


# ---------------------------------------------------------------------------
# /authorize
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorize_unauthenticated_redirects_to_login(
    oauth_client: AsyncClient,
):
    """No session cookie → 302 to /login?next=<url-encoded-original>."""
    resp = await oauth_client.get(
        "/v1/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": _TEST_CLIENT_ID,
            "redirect_uri": _TEST_REDIRECT,
            "state": "abc",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("/login?next=")
    # Original querystring must be preserved (URL-encoded) as the next param.
    parsed = parse_qs(urlparse(location).query)
    assert "next" in parsed
    assert "/v1/oauth/authorize" in parsed["next"][0]


@pytest.mark.asyncio
async def test_authorize_invalid_client_id(
    authed_oauth_client: AsyncClient,
):
    """Wrong client_id → 400 invalid_client (no redirect)."""
    resp = await authed_oauth_client.get(
        "/v1/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "not-the-real-client",
            "redirect_uri": _TEST_REDIRECT,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "invalid_client" in resp.text


@pytest.mark.asyncio
async def test_authorize_invalid_redirect_uri(
    authed_oauth_client: AsyncClient,
):
    """Redirect URI not in the allow-list → 400 (open-redirect defence)."""
    resp = await authed_oauth_client.get(
        "/v1/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": _TEST_CLIENT_ID,
            "redirect_uri": "https://attacker.example/steal",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "invalid redirect_uri" in resp.text


@pytest.mark.asyncio
async def test_authorize_unsupported_response_type(
    authed_oauth_client: AsyncClient,
):
    """Anything other than ``response_type=code`` is rejected."""
    resp = await authed_oauth_client.get(
        "/v1/oauth/authorize",
        params={
            "response_type": "token",  # implicit-flow, not supported
            "client_id": _TEST_CLIENT_ID,
            "redirect_uri": _TEST_REDIRECT,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "unsupported_response_type" in resp.text


@pytest.mark.asyncio
async def test_authorize_happy_path_issues_code(
    authed_oauth_client: AsyncClient, kv_redis,
):
    """Authenticated user + valid params → 302 to redirect_uri with ?code=&state=."""
    resp = await authed_oauth_client.get(
        "/v1/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": _TEST_CLIENT_ID,
            "redirect_uri": _TEST_REDIRECT,
            "state": "csrf-token-123",
            "scope": "openid profile email",
            "nonce": "n-456",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    target = urlparse(resp.headers["location"])
    assert f"{target.scheme}://{target.netloc}{target.path}" == _TEST_REDIRECT
    qs = parse_qs(target.query)
    assert "code" in qs
    assert qs["state"] == ["csrf-token-123"]

    # Code should be present in the KV under the expected key prefix.
    code = qs["code"][0]
    assert any(
        k.endswith(f":{code}") for k in kv_redis._kv
    ), "code should be persisted to Redis"


@pytest.mark.asyncio
async def test_authorize_superset_access_none_denies(
    authed_oauth_client: AsyncClient, db_session,
):
    """user.superset_access='none' → 302 to redirect_uri with ?error=access_denied.

    OAuth 6749 §4.1.2.1 — error params on the redirect, never expose
    the redirect_uri to a 4xx body the browser would render.
    """
    # Flip the seeded admin's superset_access to 'none'.
    from sqlalchemy import update
    from monctl_central.storage.models import User

    await db_session.execute(
        update(User).where(User.username == "admin").values(superset_access="none")
    )
    await db_session.commit()

    resp = await authed_oauth_client.get(
        "/v1/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": _TEST_CLIENT_ID,
            "redirect_uri": _TEST_REDIRECT,
            "state": "x",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    target = urlparse(resp.headers["location"])
    qs = parse_qs(target.query)
    assert qs["error"] == ["access_denied"]
    assert qs["state"] == ["x"]


# ---------------------------------------------------------------------------
# /token
# ---------------------------------------------------------------------------


def _basic_auth_header(client_id: str, secret: str) -> dict[str, str]:
    encoded = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


@pytest.mark.asyncio
async def test_token_missing_basic_auth_returns_401(oauth_client: AsyncClient):
    resp = await oauth_client.post(
        "/v1/oauth/token",
        data={"grant_type": "authorization_code"},
    )
    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers


@pytest.mark.asyncio
async def test_token_invalid_client_secret_returns_401(oauth_client: AsyncClient):
    resp = await oauth_client.post(
        "/v1/oauth/token",
        data={"grant_type": "authorization_code", "code": "x", "redirect_uri": _TEST_REDIRECT},
        headers=_basic_auth_header(_TEST_CLIENT_ID, "wrong-secret"),
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_token_unsupported_grant_type(oauth_client: AsyncClient):
    resp = await oauth_client.post(
        "/v1/oauth/token",
        data={"grant_type": "implicit"},
        headers=_basic_auth_header(_TEST_CLIENT_ID, _TEST_CLIENT_SECRET),
    )
    assert resp.status_code == 400
    assert "unsupported_grant_type" in resp.text


@pytest.mark.asyncio
async def test_token_authorization_code_happy_path(
    authed_oauth_client: AsyncClient, oauth_client: AsyncClient,
):
    """End-to-end: /authorize → /token returns access + refresh + id_token."""
    # 1. Drive /authorize to mint a code.
    auth_resp = await authed_oauth_client.get(
        "/v1/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": _TEST_CLIENT_ID,
            "redirect_uri": _TEST_REDIRECT,
            "state": "x",
        },
        follow_redirects=False,
    )
    assert auth_resp.status_code == 302
    code = parse_qs(urlparse(auth_resp.headers["location"]).query)["code"][0]

    # 2. Redeem on /token (use the unauth oauth_client — token endpoint is
    #    purely client-secret-authenticated, no user cookie needed).
    tok_resp = await oauth_client.post(
        "/v1/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _TEST_REDIRECT,
        },
        headers=_basic_auth_header(_TEST_CLIENT_ID, _TEST_CLIENT_SECRET),
    )
    assert tok_resp.status_code == 200, tok_resp.text
    body = tok_resp.json()
    assert body["token_type"] == "Bearer"
    assert "access_token" in body
    assert "refresh_token" in body
    assert "id_token" in body
    assert isinstance(body["expires_in"], int)


@pytest.mark.asyncio
async def test_token_redirect_uri_mismatch_returns_invalid_grant(
    authed_oauth_client: AsyncClient, oauth_client: AsyncClient,
):
    """Code bound to URI A, redeemed claiming URI B → 400 invalid_grant."""
    auth_resp = await authed_oauth_client.get(
        "/v1/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": _TEST_CLIENT_ID,
            "redirect_uri": _TEST_REDIRECT,
        },
        follow_redirects=False,
    )
    code = parse_qs(urlparse(auth_resp.headers["location"]).query)["code"][0]

    resp = await oauth_client.post(
        "/v1/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            # Different (allowed-list-bypassing) URI claimed at /token.
            "redirect_uri": "https://another.example/cb",
        },
        headers=_basic_auth_header(_TEST_CLIENT_ID, _TEST_CLIENT_SECRET),
    )
    assert resp.status_code == 400
    assert "invalid_grant" in resp.text


@pytest.mark.asyncio
async def test_token_code_reuse_rejected(
    authed_oauth_client: AsyncClient, oauth_client: AsyncClient,
):
    """First redemption succeeds, second returns 400 invalid_grant.

    Codes are single-use — atomic GETDEL deletes on first read.
    """
    auth_resp = await authed_oauth_client.get(
        "/v1/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": _TEST_CLIENT_ID,
            "redirect_uri": _TEST_REDIRECT,
        },
        follow_redirects=False,
    )
    code = parse_qs(urlparse(auth_resp.headers["location"]).query)["code"][0]

    first = await oauth_client.post(
        "/v1/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _TEST_REDIRECT,
        },
        headers=_basic_auth_header(_TEST_CLIENT_ID, _TEST_CLIENT_SECRET),
    )
    assert first.status_code == 200

    second = await oauth_client.post(
        "/v1/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _TEST_REDIRECT,
        },
        headers=_basic_auth_header(_TEST_CLIENT_ID, _TEST_CLIENT_SECRET),
    )
    assert second.status_code == 400
    assert "invalid_grant" in second.text


# ---------------------------------------------------------------------------
# /userinfo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_userinfo_missing_bearer_returns_401(oauth_client: AsyncClient):
    resp = await oauth_client.get("/v1/oauth/userinfo")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_userinfo_invalid_token_returns_401(oauth_client: AsyncClient):
    resp = await oauth_client.get(
        "/v1/oauth/userinfo",
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert resp.status_code == 401
    assert "invalid_token" in resp.text


@pytest.mark.asyncio
async def test_userinfo_returns_admin_claims(
    authed_oauth_client: AsyncClient, oauth_client: AsyncClient,
):
    """End-to-end: code → access_token → /userinfo claims envelope.

    Admin role + no explicit superset_access → effective tier 'admin'
    via the role-based fallback (engine.py:139).
    """
    auth_resp = await authed_oauth_client.get(
        "/v1/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": _TEST_CLIENT_ID,
            "redirect_uri": _TEST_REDIRECT,
        },
        follow_redirects=False,
    )
    code = parse_qs(urlparse(auth_resp.headers["location"]).query)["code"][0]
    tok = (await oauth_client.post(
        "/v1/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _TEST_REDIRECT,
        },
        headers=_basic_auth_header(_TEST_CLIENT_ID, _TEST_CLIENT_SECRET),
    )).json()

    resp = await oauth_client.get(
        "/v1/oauth/userinfo",
        headers={"Authorization": f"Bearer {tok['access_token']}"},
    )
    assert resp.status_code == 200
    info = resp.json()
    assert info["preferred_username"] == "admin"
    assert info["username"] == "admin"
    assert info["role"] == "admin"
    # role=admin → all_tenants implicit (oauth.py:456) and superset_access
    # defaults to 'admin' via the role-based fallback (oauth.py:139-151).
    assert info["all_tenants"] is True
    assert info["superset_access"] == "admin"
    assert info["tenant_ids"] == []


# ---------------------------------------------------------------------------
# OIDC discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oidc_discovery_returns_full_envelope(oauth_client: AsyncClient):
    """``/v1/.well-known/openid-configuration`` carries every required field."""
    resp = await oauth_client.get("/v1/.well-known/openid-configuration")
    assert resp.status_code == 200
    body = resp.json()
    # Every endpoint URL is rooted at our configured issuer.
    assert body["issuer"] == "https://test.example"
    assert body["authorization_endpoint"].endswith("/v1/oauth/authorize")
    assert body["token_endpoint"].endswith("/v1/oauth/token")
    assert body["userinfo_endpoint"].endswith("/v1/oauth/userinfo")
    assert body["response_types_supported"] == ["code"]
    assert "authorization_code" in body["grant_types_supported"]
    assert "refresh_token" in body["grant_types_supported"]
    assert "client_secret_basic" in body["token_endpoint_auth_methods_supported"]
