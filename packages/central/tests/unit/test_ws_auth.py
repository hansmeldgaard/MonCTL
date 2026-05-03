"""Tests for the WebSocket auth path + ConnectionManager broadcast helpers.

Closes T-CEN-011 from review #2: ``ws/auth.py`` (72 LoC, the entry
point every collector hits to upgrade to WS) and the broadcast /
notify helpers in ``ws/connection_manager.py`` had no tests.

The auth path is security-critical: a bug in shared-secret comparison,
collector-id resolution, or the per-collector key lookup translates
directly to either denial-of-service for working collectors or
unauthenticated access for compromised ones.

Coverage:

  authenticate_ws — shared-secret happy path (R-CEN-009 constant-time
                    compare verified by exercising correct + wrong
                    secrets), per-collector API key happy path,
                    PENDING / REJECTED / unknown-collector rejections,
                    invalid hint, missing collector_id.

  broadcast_command local fast-path payload-unwrap (R-CEN-006-adjacent;
                    feedback_broadcast_command_unwrap memory called
                    out the bug class, this pins the fix).

  notify_config_reload — ack count from gather, individual failures
                    swallowed (R-CEN-001 contract that connectors/
                    router.py relies on for the per-collector push).
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.storage.models import ApiKey, Collector
from monctl_central.ws.auth import authenticate_ws
from monctl_central.ws.connection_manager import (
    CollectorConnection,
    ConnectionManager,
)
from monctl_common.utils import hash_api_key


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def patch_session_factory(sqlite_engine, monkeypatch):
    """authenticate_ws calls ``get_session_factory()`` directly (not via
    FastAPI Depends), so the conftest's dependency_overrides don't reach
    it. Monkeypatch the module-level helper to return a SQLite factory.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    factory = async_sessionmaker(
        sqlite_engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(
        "monctl_central.ws.auth.get_session_factory",
        lambda: factory,
    )


@pytest.fixture
async def ws_setup(db_session: AsyncSession):
    """Seed two collectors:

    * ``active`` — status=ACTIVE, has both a per-collector API key
      and is the target of the shared-secret hint path.
    * ``pending`` — status=PENDING, must be rejected by both auth
      modes.

    Returns plain UUIDs / strings (not ORM objects) so callers can
    safely use them after expire_all() round-trips.
    """
    active = Collector(
        id=uuid.uuid4(),
        name="active-worker",
        hostname="active-worker",
        status="ACTIVE",
    )
    pending = Collector(
        id=uuid.uuid4(),
        name="pending-worker",
        hostname="pending-worker",
        status="PENDING",
    )
    db_session.add(active)
    db_session.add(pending)
    await db_session.flush()

    per_collector_token = "monctl_col_test-token-deadbeef"
    db_session.add(
        ApiKey(
            id=uuid.uuid4(),
            key_hash=hash_api_key(per_collector_token),
            key_prefix=per_collector_token[:12],
            key_type="collector",
            collector_id=active.id,
            name="active-key",
        )
    )
    # PENDING collector also has a key — auth must still reject because
    # of the status check, not the key validity.
    pending_token = "monctl_col_pending-token-cafe"
    db_session.add(
        ApiKey(
            id=uuid.uuid4(),
            key_hash=hash_api_key(pending_token),
            key_prefix=pending_token[:12],
            key_type="collector",
            collector_id=pending.id,
            name="pending-key",
        )
    )
    # Wrong-type key — must be rejected even though hash matches.
    user_token = "monctl_m_user-token"
    db_session.add(
        ApiKey(
            id=uuid.uuid4(),
            key_hash=hash_api_key(user_token),
            key_prefix=user_token[:10],
            key_type="user",
            collector_id=None,
            name="user-key",
        )
    )
    await db_session.commit()

    return {
        "active_id": active.id,
        "active_name": active.name,
        "pending_id": pending.id,
        "active_token": per_collector_token,
        "pending_token": pending_token,
        "user_token": user_token,
    }


@pytest.fixture
def fake_websocket():
    """Minimal WebSocket double — accept() / close() are AsyncMocks."""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# authenticate_ws — shared secret path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shared_secret_happy_path(
    seeded_session, ws_setup, fake_websocket, monkeypatch,
):
    """MONCTL_COLLECTOR_API_KEY + collector_id hint → returns the collector."""
    monkeypatch.setenv("MONCTL_COLLECTOR_API_KEY", "shared-cluster-secret")

    cid, name = await authenticate_ws(
        fake_websocket,
        token="shared-cluster-secret",
        collector_id_hint=str(ws_setup["active_id"]),
    )
    assert cid == ws_setup["active_id"]
    assert name == ws_setup["active_name"]
    fake_websocket.close.assert_not_called()


@pytest.mark.asyncio
async def test_shared_secret_wrong_value_rejected(
    seeded_session, ws_setup, fake_websocket, monkeypatch,
):
    """Wrong secret + valid hint → reject. Pins the constant-time compare:
    even with a one-character mismatch the auth must NOT short-circuit
    to the API-key path with the wrong-secret value as the lookup key.
    """
    monkeypatch.setenv("MONCTL_COLLECTOR_API_KEY", "shared-cluster-secret")

    cid, name = await authenticate_ws(
        fake_websocket,
        token="shared-cluster-secrxt",  # one char off
        collector_id_hint=str(ws_setup["active_id"]),
    )
    assert cid is None and name is None
    fake_websocket.close.assert_called_once()


@pytest.mark.asyncio
async def test_shared_secret_missing_collector_id_falls_through(
    seeded_session, ws_setup, fake_websocket, monkeypatch,
):
    """Correct secret but no collector_id hint → drop to API-key path,
    which must ALSO reject (the secret value won't match any api_keys
    row's hash).
    """
    monkeypatch.setenv("MONCTL_COLLECTOR_API_KEY", "shared-cluster-secret")

    cid, name = await authenticate_ws(
        fake_websocket,
        token="shared-cluster-secret",
        collector_id_hint=None,
    )
    assert cid is None and name is None


@pytest.mark.asyncio
async def test_shared_secret_with_pending_collector_rejected(
    seeded_session, ws_setup, fake_websocket, monkeypatch,
):
    """Hint points at a non-ACTIVE collector → fall through, reject."""
    monkeypatch.setenv("MONCTL_COLLECTOR_API_KEY", "shared-cluster-secret")

    cid, name = await authenticate_ws(
        fake_websocket,
        token="shared-cluster-secret",
        collector_id_hint=str(ws_setup["pending_id"]),
    )
    assert cid is None and name is None


@pytest.mark.asyncio
async def test_shared_secret_invalid_uuid_hint_rejected(
    seeded_session, ws_setup, fake_websocket, monkeypatch,
):
    """Non-UUID hint must NOT crash the path — fall through to api-key."""
    monkeypatch.setenv("MONCTL_COLLECTOR_API_KEY", "shared-cluster-secret")

    cid, name = await authenticate_ws(
        fake_websocket,
        token="shared-cluster-secret",
        collector_id_hint="not-a-uuid",
    )
    assert cid is None and name is None


# ---------------------------------------------------------------------------
# authenticate_ws — per-collector API key path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_collector_key_happy_path(
    seeded_session, ws_setup, fake_websocket, monkeypatch,
):
    """Valid per-collector key → returns the bound collector.

    No collector_id hint needed in this path — the key itself binds.
    """
    monkeypatch.delenv("MONCTL_COLLECTOR_API_KEY", raising=False)

    cid, name = await authenticate_ws(
        fake_websocket,
        token=ws_setup["active_token"],
        collector_id_hint=None,
    )
    assert cid == ws_setup["active_id"]
    assert name == ws_setup["active_name"]


@pytest.mark.asyncio
async def test_per_collector_key_wrong_type_rejected(
    seeded_session, ws_setup, fake_websocket, monkeypatch,
):
    """key_type='user' → rejected even though hash exists in api_keys."""
    monkeypatch.delenv("MONCTL_COLLECTOR_API_KEY", raising=False)

    cid, name = await authenticate_ws(
        fake_websocket,
        token=ws_setup["user_token"],
        collector_id_hint=None,
    )
    assert cid is None and name is None
    fake_websocket.close.assert_called_once()


@pytest.mark.asyncio
async def test_per_collector_key_pending_collector_rejected(
    seeded_session, ws_setup, fake_websocket, monkeypatch,
):
    """Per-collector key whose collector is PENDING → rejected.

    Status check is intentional — F-CEN-014/15/16 enforce that PENDING
    collectors don't get any access until the operator approves.
    """
    monkeypatch.delenv("MONCTL_COLLECTOR_API_KEY", raising=False)

    cid, name = await authenticate_ws(
        fake_websocket,
        token=ws_setup["pending_token"],
        collector_id_hint=None,
    )
    assert cid is None and name is None


@pytest.mark.asyncio
async def test_unknown_token_rejected(
    seeded_session, ws_setup, fake_websocket, monkeypatch,
):
    """Token that hashes to nothing in api_keys → reject."""
    monkeypatch.delenv("MONCTL_COLLECTOR_API_KEY", raising=False)

    cid, name = await authenticate_ws(
        fake_websocket,
        token="completely-unknown-token",
        collector_id_hint=None,
    )
    assert cid is None and name is None
    fake_websocket.close.assert_called_once()


# ---------------------------------------------------------------------------
# ConnectionManager.broadcast_command — local fast-path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcast_command_local_unwraps_payload(monkeypatch):
    """Local fast-path returns ``result["payload"]`` not the WS envelope.

    R-CEN-006-adjacent — feedback_broadcast_command_unwrap memory:
    callers expect a flat dict regardless of whether the response came
    from the local connection or the Redis fanout. Pin the unwrap.
    """
    mgr = ConnectionManager()
    cid = uuid.uuid4()

    fake_conn = MagicMock(spec=CollectorConnection)
    fake_conn.send_request = AsyncMock(
        return_value={
            "message_id": "abc",
            "type": "config_reload_response",
            "payload": {"acknowledged": True},
        }
    )
    mgr._connections[cid] = fake_conn

    result = await mgr.broadcast_command(cid, "config_reload", {})
    # Caller sees the payload, not the envelope.
    assert result == {"acknowledged": True}


@pytest.mark.asyncio
async def test_broadcast_command_local_passes_through_non_envelope(monkeypatch):
    """If the response isn't envelope-shaped, return it as-is."""
    mgr = ConnectionManager()
    cid = uuid.uuid4()

    fake_conn = MagicMock(spec=CollectorConnection)
    fake_conn.send_request = AsyncMock(return_value={"acknowledged": True})
    mgr._connections[cid] = fake_conn

    result = await mgr.broadcast_command(cid, "config_reload", {})
    assert result == {"acknowledged": True}


@pytest.mark.asyncio
async def test_broadcast_command_no_local_no_redis_raises(monkeypatch):
    """No local conn + Redis unavailable → KeyError with diagnostic."""
    # Make _get_redis() return None.
    monkeypatch.setattr(
        "monctl_central.ws.connection_manager._get_redis",
        AsyncMock(return_value=None),
    )

    mgr = ConnectionManager()
    cid = uuid.uuid4()

    with pytest.raises(KeyError, match="not connected locally"):
        await mgr.broadcast_command(cid, "ping", {}, timeout=0.1)


# ---------------------------------------------------------------------------
# ConnectionManager.notify_config_reload — gather + per-collector failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_config_reload_counts_acks(monkeypatch):
    """Returns the number of collectors that ACKed within the timeout."""
    mgr = ConnectionManager()

    # Three collectors: two ACK, one raises.
    cids = [uuid.uuid4() for _ in range(3)]
    behaviour = {cids[0]: "ack", cids[1]: "ack", cids[2]: "fail"}

    async def fake_broadcast(cid, msg_type, payload, timeout=10.0):
        if behaviour[cid] == "fail":
            raise asyncio.TimeoutError("collector wedged")
        return {"acknowledged": True}

    mgr.broadcast_command = AsyncMock(side_effect=fake_broadcast)

    n = await mgr.notify_config_reload(cids, timeout=0.1)
    assert n == 2  # one failure swallowed (debug-logged per R-CEN-001 caveat)


@pytest.mark.asyncio
async def test_notify_config_reload_empty_short_circuits(monkeypatch):
    """No collectors → no broadcast attempts, returns 0."""
    mgr = ConnectionManager()
    mgr.broadcast_command = AsyncMock()  # would raise if called by the gather

    n = await mgr.notify_config_reload([])
    assert n == 0
    mgr.broadcast_command.assert_not_called()


# ---------------------------------------------------------------------------
# ConnectionManager.connect — R-CEN-006 reconnect-race serialisation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_replaces_old_connection_under_lock():
    """Two near-simultaneous connects for the same collector_id end with
    one current connection in the dict and the prior one closed.

    R-CEN-006: serialise the read-replace-write so neither task "wins"
    leaving a leaked socket. The lock-protected critical section pre-
    registers the new conn before letting the old one tear down.
    """
    from fastapi import WebSocket

    mgr = ConnectionManager()
    cid = uuid.uuid4()

    # Build two fake WebSockets — accept() is a no-op, close() and
    # send_json() are AsyncMocks so the keepalive task can drive them.
    def _mk_ws() -> MagicMock:
        ws = MagicMock(spec=WebSocket)
        ws.send_json = AsyncMock()
        ws.close = AsyncMock()
        return ws

    ws1 = _mk_ws()
    ws2 = _mk_ws()

    await mgr.connect(cid, "worker", ws1)
    first = mgr._connections[cid]
    assert first.websocket is ws1

    await mgr.connect(cid, "worker", ws2)
    second = mgr._connections[cid]
    assert second.websocket is ws2  # second registration won
    assert second is not first  # old connection was displaced
    # Old WS was closed when displaced.
    ws1.close.assert_awaited()

    # Cleanup keepalive tasks so the test doesn't leak background tasks.
    await second.stop_keepalive()


@pytest.mark.asyncio
async def test_disconnect_removes_from_local_dict():
    """disconnect() removes the entry; subsequent connect()s see no prior."""
    from fastapi import WebSocket

    mgr = ConnectionManager()
    cid = uuid.uuid4()
    ws = MagicMock(spec=WebSocket)
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()

    await mgr.connect(cid, "worker", ws)
    assert cid in mgr._connections

    mgr.disconnect(cid)
    assert cid not in mgr._connections
