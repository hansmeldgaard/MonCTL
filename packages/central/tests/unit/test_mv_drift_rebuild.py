"""Tests for `_ensure_mv_drift_rebuild` (M-CEN-005).

This helper drives the guarded DROP+CREATE for `*_latest` MVs that
have drifted off the canonical DDL — `execution_time` column added
to `config_latest`/`interface_latest`, `assignment_id` added to
`performance_latest` ORDER BY, etc. CH 24.3 rejects ALTER ADD COLUMN
on MVs and silently ignores ALTER MODIFY ORDER BY, so the helper is
the only safe migration path; getting it wrong wipes the MV every
restart (no-op check) or silently leaves it stale (false-positive on
the check).

The pysnmp-style sys.modules stub from `test_clickhouse_pool.py`
covers the module's import-time pysnmp/clickhouse_connect bindings.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _install_ch_stub() -> None:
    if "clickhouse_connect" in sys.modules:
        return
    ch = types.ModuleType("clickhouse_connect")
    drv = types.ModuleType("clickhouse_connect.driver")
    drv_client = types.ModuleType("clickhouse_connect.driver.client")
    drv_httpclient = types.ModuleType("clickhouse_connect.driver.httpclient")

    class Client:  # noqa: D401
        valid_transport_settings = frozenset()

    class HttpClient(Client):  # noqa: D401
        valid_transport_settings = frozenset()

    drv_client.Client = Client
    drv_httpclient.HttpClient = HttpClient
    drv.client = drv_client
    drv.httpclient = drv_httpclient
    ch.driver = drv
    ch.get_client = lambda **_: Client()  # pragma: no cover
    sys.modules["clickhouse_connect"] = ch
    sys.modules["clickhouse_connect.driver"] = drv
    sys.modules["clickhouse_connect.driver.client"] = drv_client
    sys.modules["clickhouse_connect.driver.httpclient"] = drv_httpclient


_install_ch_stub()


from monctl_central.storage.clickhouse import _ensure_mv_drift_rebuild  # noqa: E402


# ── Fake client ────────────────────────────────────────────────────────────


class _FakeQueryResult:
    def __init__(self, rows):
        self.result_rows = rows
        self.first_row = rows[0] if rows else None


def _make_client(*, ctq: str = "", sort_key: str = "", row_present: bool = True):
    """Build a fake CH client with controllable system.tables row + capturing
    `command()` for assertions.
    """
    rows = [(ctq, sort_key)] if row_present else []
    client = MagicMock()
    client.query = MagicMock(return_value=_FakeQueryResult(rows))
    client.command = MagicMock(return_value=None)
    return client


# ── Helper signature ───────────────────────────────────────────────────────


_DDL_CLUSTER = "CREATE MATERIALIZED VIEW IF NOT EXISTS my_mv ON CLUSTER '{cluster}' AS SELECT * FROM base"
_DDL_LOCAL = "CREATE MATERIALIZED VIEW IF NOT EXISTS my_mv AS SELECT * FROM base"


# ── Test cases ─────────────────────────────────────────────────────────────


def test_no_op_when_mv_not_in_system_tables() -> None:
    """If `system.tables` returns 0 rows, the MV doesn't exist yet and the
    earlier `CREATE MATERIALIZED VIEW IF NOT EXISTS` will create it — the
    helper must not issue a DROP."""
    client = _make_client(row_present=False)
    _ensure_mv_drift_rebuild(
        client, "my_mv", _DDL_CLUSTER, _DDL_LOCAL,
        has_cluster=False, cluster_name="monctl",
        expected_columns={"execution_time"},
    )
    client.command.assert_not_called()


def test_no_op_when_all_expected_columns_present() -> None:
    """create_table_query contains the expected column → no rebuild."""
    client = _make_client(
        ctq="CREATE MATERIALIZED VIEW config_latest ENGINE=ReplicatedReplacingMergeTree "
            "AS SELECT assignment_id, execution_time, ... FROM config",
    )
    _ensure_mv_drift_rebuild(
        client, "config_latest", _DDL_CLUSTER, _DDL_LOCAL,
        has_cluster=False, cluster_name="monctl",
        expected_columns={"execution_time"},
    )
    client.command.assert_not_called()


def test_rebuilds_when_column_missing_from_ctq() -> None:
    """DROP + CREATE issued when an expected column isn't in the DDL."""
    client = _make_client(
        ctq="CREATE MATERIALIZED VIEW config_latest AS SELECT assignment_id FROM config",
    )
    _ensure_mv_drift_rebuild(
        client, "config_latest", _DDL_CLUSTER, _DDL_LOCAL,
        has_cluster=False, cluster_name="monctl",
        expected_columns={"execution_time"},
    )
    cmds = [c.args[0] for c in client.command.call_args_list]
    assert len(cmds) == 2
    assert cmds[0] == "DROP TABLE IF EXISTS config_latest"
    assert cmds[1] == _DDL_LOCAL


def test_rebuilds_when_sort_key_missing_term() -> None:
    """`performance_latest` needs `assignment_id` in ORDER BY → drift detected
    via `sorting_key`, not via column presence."""
    client = _make_client(
        ctq="<...>",
        sort_key="device_id, component_type, component",
    )
    _ensure_mv_drift_rebuild(
        client, "performance_latest", _DDL_CLUSTER, _DDL_LOCAL,
        has_cluster=False, cluster_name="monctl",
        expected_sort_key_terms={"assignment_id"},
    )
    cmds = [c.args[0] for c in client.command.call_args_list]
    assert cmds[0] == "DROP TABLE IF EXISTS performance_latest"


def test_no_op_when_sort_key_already_contains_term() -> None:
    client = _make_client(
        sort_key="device_id, assignment_id, component_type, component",
    )
    _ensure_mv_drift_rebuild(
        client, "performance_latest", _DDL_CLUSTER, _DDL_LOCAL,
        has_cluster=False, cluster_name="monctl",
        expected_sort_key_terms={"assignment_id"},
    )
    client.command.assert_not_called()


def test_clustered_drop_includes_on_cluster_and_sync() -> None:
    """In a clustered deployment the DROP must propagate to every replica
    and SYNC so the subsequent CREATE doesn't race against still-existing
    table state on a slow replica."""
    # NB: the helper uses a substring match on `create_table_query`, so the
    # fake DDL must NOT contain the literal string `execution_time`.
    client = _make_client(ctq="CREATE MV bare AS SELECT id FROM base")
    _ensure_mv_drift_rebuild(
        client, "config_latest", _DDL_CLUSTER, _DDL_LOCAL,
        has_cluster=True, cluster_name="monctl_cluster",
        expected_columns={"execution_time"},
    )
    cmds = [c.args[0] for c in client.command.call_args_list]
    assert cmds[0] == "DROP TABLE IF EXISTS config_latest ON CLUSTER 'monctl_cluster' SYNC"
    # Cluster path uses the format-substituted DDL
    assert "ON CLUSTER 'monctl_cluster'" in cmds[1]


def test_local_path_uses_local_ddl_string_unchanged() -> None:
    client = _make_client(ctq="CREATE MV bare AS SELECT id FROM base")
    _ensure_mv_drift_rebuild(
        client, "config_latest", _DDL_CLUSTER, _DDL_LOCAL,
        has_cluster=False, cluster_name="monctl",
        expected_columns={"execution_time"},
    )
    cmds = [c.args[0] for c in client.command.call_args_list]
    # Standalone — no ON CLUSTER, exact local DDL
    assert "ON CLUSTER" not in cmds[0]
    assert cmds[1] == _DDL_LOCAL


def test_query_exception_is_swallowed_logged() -> None:
    """If the system.tables probe blows up (CH outage, permission), the helper
    must not raise — startup migration loop catches per-MV. Verify no DROP
    issued and no exception propagates."""
    client = MagicMock()
    client.query.side_effect = ConnectionError("CH unreachable")
    client.command = MagicMock()

    _ensure_mv_drift_rebuild(
        client, "config_latest", _DDL_CLUSTER, _DDL_LOCAL,
        has_cluster=False, cluster_name="monctl",
        expected_columns={"execution_time"},
    )
    # Failed before even checking → no DROP
    client.command.assert_not_called()


def test_multiple_missing_signals_still_only_one_rebuild() -> None:
    """Both column AND sort-key missing → still single DROP+CREATE pair."""
    client = _make_client(ctq="<bare>", sort_key="device_id")
    _ensure_mv_drift_rebuild(
        client, "config_latest", _DDL_CLUSTER, _DDL_LOCAL,
        has_cluster=False, cluster_name="monctl",
        expected_columns={"execution_time", "rtt_ms"},
        expected_sort_key_terms={"assignment_id"},
    )
    assert client.command.call_count == 2
