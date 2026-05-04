"""Tests for `automations/executor.py:execute_action_locally`.

Closes the env-allowlist half of S-CEN-010. The previous implementation
inherited `os.environ.copy()` into the user-authored action subprocess,
which meant `MONCTL_ENCRYPTION_KEY`, `MONCTL_JWT_SECRET_KEY`, the DB DSN
with password, OAuth client secret, collector API key, peer token, and
every other secret the central process holds were one ``print
os.environ`` away from any user with `automation:create`.

These tests pin the new contract:
1. The subprocess does NOT see MONCTL_* parent env (secrets stay home).
2. The wrapper-internal vars (`MONCTL_ACTION_CONTEXT`,
   `MONCTL_ACTION_OUTPUT`) are still set — they are needed to deliver
   context + collect output.
3. A small allowlist of system vars (PATH, HOME, LANG, ...) propagates,
   so user scripts that rely on Unix conventions still work.

The router-side admin gate for `target='central'` is enforced inline at
the create / update endpoints; covering it requires a non-admin role
fixture which is substantial scaffolding — left as a follow-up.
"""

from __future__ import annotations

import asyncio
import os
import textwrap

import pytest

from monctl_central.automations.executor import execute_action_locally


@pytest.fixture
def secrets_in_parent_env(monkeypatch):
    """Stuff some MonCTL secrets into the parent env so we can prove
    the executor doesn't propagate them."""
    monkeypatch.setenv("MONCTL_ENCRYPTION_KEY", "not-the-real-key")
    monkeypatch.setenv("MONCTL_JWT_SECRET_KEY", "also-fake")
    monkeypatch.setenv("MONCTL_DATABASE_URL", "postgresql://user:pass@host/db")
    monkeypatch.setenv("MONCTL_COLLECTOR_API_KEY", "collector-secret")
    monkeypatch.setenv("MONCTL_PEER_TOKEN", "peer-secret")
    monkeypatch.setenv("MONCTL_OAUTH_CLIENT_SECRET", "oauth-secret")
    yield


@pytest.mark.asyncio
async def test_executor_does_not_propagate_monctl_secrets(secrets_in_parent_env) -> None:
    """The user script sees an env with no MONCTL_* secret keys.

    Reads `os.environ` and emits the keys that start with `MONCTL_`. The
    only ones the wrapper itself sets are `MONCTL_ACTION_CONTEXT` and
    `MONCTL_ACTION_OUTPUT`; nothing else.
    """
    src = textwrap.dedent(
        """
        import os
        leaked = sorted(k for k in os.environ if k.startswith("MONCTL_"))
        context.set_output("leaked", leaked)
        """
    )
    result = await execute_action_locally(src, {})
    assert result["status"] == "success", result["stderr"]
    assert result["output_data"]["leaked"] == [
        "MONCTL_ACTION_CONTEXT",
        "MONCTL_ACTION_OUTPUT",
    ]


@pytest.mark.asyncio
async def test_executor_propagates_safe_system_envvars() -> None:
    """PATH must reach the subprocess — otherwise `python3` etc. would
    be unfindable, breaking even trivial action scripts."""
    src = textwrap.dedent(
        """
        import os
        context.set_output("has_path", "PATH" in os.environ)
        context.set_output("path_value", os.environ.get("PATH", ""))
        """
    )
    result = await execute_action_locally(src, {})
    assert result["status"] == "success", result["stderr"]
    assert result["output_data"]["has_path"] is True
    assert result["output_data"]["path_value"]  # non-empty


@pytest.mark.asyncio
async def test_executor_action_context_is_delivered() -> None:
    """The wrapper passes context_data through MONCTL_ACTION_CONTEXT."""
    src = textwrap.dedent(
        """
        context.set_output("device_name", context.device_name)
        context.set_output("trigger_type", context.trigger_type)
        """
    )
    result = await execute_action_locally(
        src,
        {"device_name": "router-1", "trigger_type": "manual"},
    )
    assert result["status"] == "success", result["stderr"]
    assert result["output_data"]["device_name"] == "router-1"
    assert result["output_data"]["trigger_type"] == "manual"


@pytest.mark.asyncio
async def test_executor_returns_failed_on_nonzero_exit() -> None:
    src = "raise SystemExit(7)"
    result = await execute_action_locally(src, {})
    assert result["status"] == "failed"
    assert result["exit_code"] == 7


@pytest.mark.asyncio
async def test_executor_returns_timeout_when_script_hangs() -> None:
    src = "import time; time.sleep(10)"
    result = await execute_action_locally(src, {}, timeout=1)
    assert result["status"] == "timeout"
    assert "timed out" in result["stderr"].lower()
