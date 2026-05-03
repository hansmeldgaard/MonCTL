"""Unit tests for the ClickHouse client pool.

Pins the behaviour introduced when `_LockedClient` (single-client + global
RLock) was replaced with `_ClientPool` + `_PooledClient`:

  * Sequential callers reuse a single slot (LIFO) instead of rotating
    through every pool position and forcing each slot to materialise a
    client. This keeps connection counts low under light load.
  * Concurrent callers spread across distinct slots so CH queries run
    in parallel (the win over the previous global RLock).
  * A connection error discards the borrowed slot; the next acquire
    rebuilds a fresh client from the factory.
  * Non-connection errors leave the slot intact (client is reused).
"""
from __future__ import annotations

import contextlib
import sys
import types
from concurrent.futures import ThreadPoolExecutor


def _install_ch_stub() -> None:
    if "clickhouse_connect" in sys.modules:
        return
    ch = types.ModuleType("clickhouse_connect")
    drv = types.ModuleType("clickhouse_connect.driver")
    drv_client = types.ModuleType("clickhouse_connect.driver.client")

    class Client:  # noqa: D401 — stand-in for the real clickhouse_connect.Client
        pass

    drv_client.Client = Client
    drv.client = drv_client
    ch.driver = drv
    ch.get_client = lambda **_: Client()  # pragma: no cover — never invoked here
    sys.modules["clickhouse_connect"] = ch
    sys.modules["clickhouse_connect.driver"] = drv
    sys.modules["clickhouse_connect.driver.client"] = drv_client


_install_ch_stub()

from monctl_central.storage.clickhouse import _ClientPool, _PooledClient  # noqa: E402


class _FakeClient:
    def __init__(self, tag: int):
        self.tag = tag
        self.closed = False

    def query(self, sql: str, **_kwargs) -> str:
        return f"{self.tag}:{sql}"

    def close(self) -> None:
        self.closed = True


def _counting_factory():
    """Factory that hands out FakeClient(1), FakeClient(2), ... in order."""
    counter = {"n": 0}

    def make() -> _FakeClient:
        counter["n"] += 1
        return _FakeClient(counter["n"])

    return make, counter


def test_pool_reuses_clients_across_acquires() -> None:
    make, counter = _counting_factory()
    pool = _ClientPool(make, size=2)
    proxy = _PooledClient(pool)

    assert proxy.query("a").endswith(":a")
    assert proxy.query("b").endswith(":b")
    # Only one client should have been instantiated (sequential calls, slot 1).
    assert counter["n"] == 1


def test_pool_serves_parallel_callers_with_distinct_clients() -> None:
    """Under concurrent load the pool must hand out distinct clients so
    queries run in parallel — this is the win over the previous
    single-client + global RLock design."""
    import threading

    counter = {"n": 0}
    gate = threading.Barrier(4)

    def make() -> "_SlowClient":
        counter["n"] += 1
        return _SlowClient(counter["n"], gate)

    pool = _ClientPool(make, size=4)
    proxy = _PooledClient(pool)

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(lambda i: proxy.query(f"q{i}"), range(4)))

    assert len(results) == 4
    # All 4 threads held a client simultaneously (the barrier would deadlock
    # otherwise — if the pool serialised through a single slot, only one
    # thread could pass the barrier at a time and the test would hang).
    assert counter["n"] == 4


class _SlowClient(_FakeClient):
    def __init__(self, tag: int, gate):
        super().__init__(tag)
        self._gate = gate

    def query(self, sql: str, **_kwargs) -> str:
        # All 4 threads must reach this barrier before any can proceed.
        self._gate.wait(timeout=5.0)
        return f"{self.tag}:{sql}"


def test_connection_error_recycles_slot() -> None:
    """Broken client is closed and replaced on next acquire."""
    state = {"n": 0}

    def make() -> _FakeClient:
        state["n"] += 1
        n = state["n"]

        class Variant(_FakeClient):
            def query(self, sql: str, **_kwargs):
                if n == 1:
                    raise ConnectionError("broken pipe")
                return f"v{n}:{sql}"

        return Variant(n)

    pool = _ClientPool(make, size=1)
    proxy = _PooledClient(pool)

    first_raised = False
    try:
        proxy.query("x")
    except ConnectionError:
        first_raised = True
    assert first_raised, "proxy must propagate ConnectionError — not swallow it"

    # Slot was recycled; factory ran again to build a healthy client.
    assert proxy.query("y") == "v2:y"
    assert state["n"] == 2


def test_non_connection_error_preserves_slot() -> None:
    """Logic errors must not discard the client — it's still healthy."""
    make, counter = _counting_factory()

    class _Boom(_FakeClient):
        def query(self, sql: str, **_kwargs):
            raise ValueError("bad sql")

    def factory():
        counter["n"] += 1
        return _Boom(counter["n"])

    pool = _ClientPool(factory, size=1)
    proxy = _PooledClient(pool)

    for _ in range(3):
        with contextlib.suppress(ValueError):
            proxy.query("x")

    # Factory ran once — the same client stayed in the slot across errors.
    assert counter["n"] == 1


def test_broken_factory_restores_slot() -> None:
    """If the factory raises while the slot is borrowed, the slot must be
    returned to the pool (as None) so the next caller can try again.
    Otherwise a single transient CH outage during startup would permanently
    deadlock the pool.
    """
    attempts = {"n": 0}

    def make() -> _FakeClient:
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise ConnectionError("CH unreachable")
        return _FakeClient(attempts["n"])

    pool = _ClientPool(make, size=1)
    proxy = _PooledClient(pool)

    for _ in range(2):
        with contextlib.suppress(ConnectionError):
            proxy.query("x")

    # Third attempt succeeds — the slot was always returned after failed
    # factory calls.
    assert proxy.query("ok") == "3:ok"
