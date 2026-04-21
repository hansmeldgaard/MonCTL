"""F-X-001 Phase 1: `require_collector_auth` accepts per-collector API keys.

The dependency must:
  1. Accept a valid per-collector API key (from `api_keys` table) and return
     `auth["collector_id"]` so scope enforcement can key off the caller.
  2. Accept the legacy shared secret (`MONCTL_COLLECTOR_API_KEY`) as a
     bootstrap fallback — no `collector_id` in that path.
  3. Reject unknown bearer tokens (falls through to `require_auth`, which
     raises 401 for bearers that aren't management API keys or JWTs).

We patch the two DB-touching helpers — `_validate_api_key` and
`require_auth` — so the test stays a pure unit test without a Postgres
fixture.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from monctl_central.dependencies import require_collector_auth


def _mk_request() -> Request:
    """Bare Starlette request with empty headers — enough for the code path."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/jobs",
        "headers": [],
    }
    return Request(scope)


def _mk_creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.mark.asyncio
async def test_per_collector_key_returns_collector_id(monkeypatch):
    monkeypatch.delenv("MONCTL_COLLECTOR_API_KEY", raising=False)

    fake_key = {
        "key_type": "collector",
        "collector_id": "11111111-1111-1111-1111-111111111111",
        "scopes": ["collector:*"],
        "auth_type": "api_key",
        "tenant_ids": None,
    }
    with patch(
        "monctl_central.dependencies._validate_api_key",
        new=AsyncMock(return_value=fake_key),
    ):
        auth = await require_collector_auth(
            _mk_request(), _mk_creds("monctl_c_abc"), db=None
        )

    assert auth["auth_type"] == "collector_api_key"
    assert auth["collector_id"] == "11111111-1111-1111-1111-111111111111"
    assert auth["tenant_ids"] is None


@pytest.mark.asyncio
async def test_shared_secret_still_works_as_fallback(monkeypatch):
    """Legacy bootstrap path — no per-collector key in the DB but the
    fleet-wide secret matches. No `collector_id` on the returned dict."""
    monkeypatch.setenv("MONCTL_COLLECTOR_API_KEY", "shared-xyz")

    # _validate_api_key is NOT reached when the token equals the shared secret.
    with patch(
        "monctl_central.dependencies._validate_api_key",
        new=AsyncMock(side_effect=AssertionError("shared-secret short-circuit broke")),
    ):
        auth = await require_collector_auth(
            _mk_request(), _mk_creds("shared-xyz"), db=None
        )

    assert auth["auth_type"] == "collector_shared_secret"
    assert "collector_id" not in auth


@pytest.mark.asyncio
async def test_unknown_token_falls_through_to_require_auth(monkeypatch):
    monkeypatch.setenv("MONCTL_COLLECTOR_API_KEY", "shared-xyz")

    async def _raise_401(token):
        raise HTTPException(status_code=401, detail="Invalid API key")

    async def _require_auth_raises(*_args, **_kwargs):
        raise HTTPException(status_code=401, detail="Authentication required")

    with patch(
        "monctl_central.dependencies._validate_api_key",
        new=AsyncMock(side_effect=_raise_401),
    ), patch(
        "monctl_central.dependencies.require_auth",
        new=AsyncMock(side_effect=_require_auth_raises),
    ):
        with pytest.raises(HTTPException) as excinfo:
            await require_collector_auth(
                _mk_request(), _mk_creds("garbage-token"), db=None
            )
    assert excinfo.value.status_code == 401


@pytest.mark.asyncio
async def test_management_key_rejected_on_collector_endpoints(monkeypatch):
    """Management keys must not masquerade as collectors on /api/v1/*.

    The branch in require_collector_auth only unpacks to the fast
    `collector_api_key` path when `key_type == "collector"`; anything else
    falls through to `require_auth`, which accepts management keys but
    without the `collector_id` context."""
    monkeypatch.delenv("MONCTL_COLLECTOR_API_KEY", raising=False)

    management_key = {
        "key_type": "management",
        "collector_id": None,
        "scopes": ["*"],
        "auth_type": "api_key",
        "tenant_ids": None,
    }

    async def _fallback(*_args, **_kwargs):
        return {"auth_type": "api_key", "key_type": "management", "tenant_ids": None}

    with patch(
        "monctl_central.dependencies._validate_api_key",
        new=AsyncMock(return_value=management_key),
    ), patch(
        "monctl_central.dependencies.require_auth",
        new=AsyncMock(side_effect=_fallback),
    ) as mock_auth:
        auth = await require_collector_auth(
            _mk_request(), _mk_creds("monctl_m_xyz"), db=None
        )

    assert auth["auth_type"] == "api_key"
    assert mock_auth.await_count == 1  # fell through to require_auth
