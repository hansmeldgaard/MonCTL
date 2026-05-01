# Migration Safety Findings — Review #2 (2026-04-30)

## Summary

19 findings: 4 HIGH / 9 MED / 6 LOW. Alembic chain is healthy (single head `af7g8h9i0j1k_drop_analytics_dashboards`, no dup IDs, no branch points, 98 revisions clean), and the OS-install-resume flow is solid. The biggest hole is the customer installer: `init --force` regenerates **all** secrets including JWT/encryption/DB passwords, and the rollout topology bypasses the per-collector registration flow that PR #120-#122 introduced. ClickHouse DDL has two correctness gaps around schema drift on cluster ALTERs. The rollup chain is regressed against memory `project_rollup_chain_fragility`.

---

## Alembic chain integrity

### M-CEN-001 — Frozen-literal migration carries dev-cluster timestamp
- **Severity**: LOW
- **File**: `packages/central/alembic/versions/zv2w3x4y5z6a_fix_os_install_jobs_created_at.py:25,39`
- **Description**: `FROZEN_DEFAULT = "2026-04-02 21:44:16.534462+00"` is a literal pulled from the dev cluster. Any other operator's cluster won't have this exact value, so the backfill is a no-op. Fine on fresh installs; if a customer hits the same column-default-frozen bug we hit, this migration won't catch it.
- **Fix sketch**: Detect the bug pattern instead of matching one literal: `WHERE created_at < started_at AND created_at = (SELECT min(created_at) FROM os_install_jobs)`.

### M-CEN-002 — Two migrations have empty `downgrade()` bodies
- **Severity**: LOW
- **Files**:
  - `packages/central/alembic/versions/zk1l2m3n4o5p_drop_os_cached_packages.py:20-22`
  - `packages/central/alembic/versions/zv2w3x4y5z6a_fix_os_install_jobs_created_at.py:43-45`
- **Description**: Both `downgrade()` bodies just `pass`. Acceptable for the dropped-table case but means a panic-revert can't restore prior schema/data.
- **Fix sketch**: Document the no-op in the docstring (already done) and accept. Or for the first one, recreate the dropped table shell.

---

## ClickHouse DDL idempotence

### M-CEN-003 — `ALTER TABLE ADD COLUMN IF NOT EXISTS` runs without ON CLUSTER on cluster setups
- **Severity**: HIGH
- **File**: `packages/central/src/monctl_central/storage/clickhouse.py:1832-1881, 1971-2003`
- **Description**: All 30+ `ALTER TABLE` column adds and `ADD INDEX` statements in `_TENANT_NAME_ALTERS` and `_INDEXES` lists fire **without** `ON CLUSTER`. In a multi-replica setup (CH on central3+central4), each central node connects to its own CH host. If only one node runs the migration, the other replica diverges on schema. Subsequent inserts replicate the row but the missing-column replica drops/ignores the new fields. Worse, `try/except: pass` silently swallows errors so drift is invisible.
- **Fix sketch**: Wrap all 30+ ALTERs in `if has_cluster: stmt += " ON CLUSTER '{cluster}'"`. At minimum, log the swallowed exception at WARNING so drift is observable.

### M-CEN-004 — `_INDEXES` swallows errors silently and never propagates to other replicas
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/storage/clickhouse.py:1971-2008`
- **Description**: Same pattern as M-CEN-003 — `ALTER TABLE … ADD INDEX IF NOT EXISTS` runs without `ON CLUSTER`. If the index gets added on shard A but not shard B, queries that should hit the bloom filter fall back to a full-merge-scan on B. Performance regression that no error surfaces.
- **Fix sketch**: Same as M-CEN-003.

### M-CEN-005 — `*_latest` MV column-drift detection only covers `execution_time`
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/storage/clickhouse.py:1888-1931`
- **Description**: The guarded DROP+CREATE only checks `position(create_table_query, 'execution_time')` for `config_latest` and `interface_latest`. Per memory `feedback_ch_mv_schema_migrations`: any future column add to `availability_latency_latest` or `performance_latest` requires a fresh guarded check. Every new MV column needs another bespoke `if "<colname>" not in create_table_query` block, easy to forget.
- **Fix sketch**: Either drive MV recreation off a hash of the canonical DDL string vs `system.tables.create_table_query`, or move the check into a helper `_ensure_mv_columns(name, expected_cols)` that compares `system.columns` to the expected set and rebuilds when mismatched.

### M-CEN-006 — `try/except: pass` around schema migration loop swallows everything
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/storage/clickhouse.py:1882-1886, 2004-2008`
- **Description**: Both the ALTER COLUMN loop and the ADD INDEX loop catch all exceptions silently. A typo in a DDL statement would never surface in logs.
- **Fix sketch**: At minimum, `logger.warning("ddl_alter_failed sql=%s", alter_sql, exc_info=True)`. Better: distinguish "column already exists" (benign) from "syntax error" (fatal) by not relying on `IF NOT EXISTS` to swallow real errors.

---

## OS upgrade flow

### M-CEN-007 — Lease loss in `_refresh_driver_lease` doesn't cancel the driving task
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/upgrades/os_service.py:369-396`
- **Description**: When `_refresh_driver_lease` returns early because another central acquired the lease, the driving `_run_steps` body keeps running and mutating PG rows. Two centrals could race step transitions if there's clock-skew + network-blip + a stuck `apt-get install`. PG row locks serialise mutations but the second central's `execute_os_install_job` may have already issued a `started_at`/`status` update that the first one overwrites.
- **Fix sketch**: Pass a `stop_event: asyncio.Event` from `execute_os_install_job` to the refresher; on lease loss, set the event, and check it in `_run_steps` between iterations. Or: cancel the parent task via `task.cancel()` from the refresher.

### M-CEN-008 — `dpkg --configure -a` exit code is discarded; failure masked by apt-get
- **Severity**: LOW
- **File**: `docker/docker-stats-server.py:820-824`
- **Description**: `( dpkg --configure -a; apt-get install -y … )` chains with `;` not `&&`. If dpkg recovery itself fails, apt-get runs anyway and likely fails too — but the user only sees the apt-get error in the log, not the dpkg failure.
- **Fix sketch**: Capture dpkg's stderr separately, or `set -o pipefail` + tee; surface a "dpkg recovery failed" warning in `step.output_log` even when apt-get later succeeds.

### M-CEN-009 — Resume of orphan running-install steps is rate-unlimited
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/scheduler/tasks.py:1196-1244`
- **Description**: `_resume_orphaned_os_jobs` runs every scheduler tick on the leader; if a job legitimately stays `running` for 10+ minutes (slow apt download), every tick will see it in `orphans`, hit the lease check, and skip — fine. But the `self._active_os_jobs.add()` happens *before* lease acquisition, with no counter. If the lease check fails repeatedly (Redis blip), the set could accumulate stale entries on the same instance.
- **Fix sketch**: Move `add()` after successful lease acquisition, or rely on `_clear_tracking` callback to do the cleanup correctly.

---

## Customer installer — secrets + topology

### M-INST-010 — `init --force` regenerates ALL secrets, can wipe prod cluster auth
- **Severity**: HIGH
- **File**: `packages/installer/src/monctl_installer/commands/init.py:170-174`
- **Description**: `_finalize` unconditionally calls `generate_secrets()` and `write_secrets(bundle, secrets_path, overwrite=True)`. If an operator runs `init --force` to fix a typo in inventory (or to add a host they should have used `add-host` for), every secret is rotated: `MONCTL_JWT_SECRET_KEY` (invalidates all sessions), `MONCTL_ENCRYPTION_KEY` (every credential at rest becomes undecryptable), `PG_PASSWORD` (DB connections fail until manual reset on PG side), `MONCTL_COLLECTOR_API_KEY` (every collector immediately drops out), `MONCTL_OAUTH_CLIENT_SECRET` (Superset SSO breaks). Catastrophic on a running cluster.
- **Fix sketch**: When `secrets_path.exists()`, load+preserve existing values, regenerate only fields the operator explicitly asks to rotate via a separate `monctl_ctl secrets rotate <field>` subcommand. `init --force` should refuse if `secrets_path` exists; require an explicit flag `--regenerate-secrets`.

### M-INST-011 — Installer ships shared collector API key; bypasses per-collector auth (PR #120-#122)
- **Severity**: HIGH
- **File**: `packages/installer/src/monctl_installer/render/templates/compose/collector.yml.j2:13,17,45,67`
- **Description**: Every worker compose template injects the same `MONCTL_COLLECTOR_API_KEY` from `secrets.env`. The collector-entrypoint sees it already set and **skips** the `MONCTL_REGISTRATION_TOKEN` flow entirely (`docker/collector-entrypoint.sh:31-32`). Per memory PRs #120-#122, central added `F-CEN-014` to "reject cross-collector /jobs queries on per-collector auth" — but installer-deployed clusters never opt into per-collector auth. Loss of one collector's secret == loss of all.
- **Fix sketch**: Drop the shared-key-as-API-key emission from the template. Generate a per-host registration token at `init` time (or use `MONCTL_COLLECTOR_API_KEY` only as the **registration secret**), set `MONCTL_REGISTRATION_TOKEN` per host, let the entrypoint register and persist a unique credentials.json.

### M-INST-012 — Installer ships shared `PEER_TOKEN` to every worker
- **Severity**: MED
- **File**: `packages/installer/src/monctl_installer/render/templates/env/collector.env.j2:3`; `secrets/generator.py:30,73`
- **Description**: Per memory `project_peer_token_per_host`, "Each worker has a unique PEER_TOKEN in /opt/monctl/collector/.env (F-COL-026) — preserve on redeploy, never reset". The installer puts ONE generated `peer_token` into `secrets.env` and templates it into every worker's compose. A leaked PEER_TOKEN from one worker compromises the gRPC channel on every worker.
- **Fix sketch**: Generate `peer_token` per-host at render time (e.g. `secrets.token_urlsafe(32)` keyed by `host.name`, persisted in a per-host secrets file). Or accept the cluster-wide scope and update `project_peer_token_per_host` memory.

### M-INST-013 — `_wait_healthy` regex match is wrong for `/v1/health` response
- **Severity**: HIGH
- **File**: `packages/installer/src/monctl_installer/commands/upgrade.py:197-200`
- **Description**: The canary health check runs `curl … /v1/health` and the upgrade aborts unless the response contains `"success"`. But `/v1/health` returns `{"status": "healthy", "version": ..., "instance_id": ...}` (`packages/central/src/monctl_central/main.py:701-704`) — there is no `"success"` substring. The unit test seeds `'{"status":"success"}'` (`packages/installer/tests/test_upgrade.py:38`) which masks the bug.
- **Real-world effect**: Every `monctl_ctl upgrade` will hit `health_timeout_s` and abort with `UpgradeAborted("canary X unhealthy after upgrade")` even when the canary is perfectly healthy.
- **Fix sketch**: Match `"healthy"` not `"success"` (line 199), or parse JSON and check `payload.get("status") == "healthy"`. Update the test fixture to mirror real response.

### M-INST-014 — Air-gap bundle has no integrity check on load
- **Severity**: MED
- **File**: `packages/installer/src/monctl_installer/commands/bundle.py:122-147`
- **Description**: `load_bundle` blindly `tar.extractall()`s the user-supplied tarball and runs `docker load` on every `images/*.tar`. No SHA-256 manifest, no signature, no version check that the bundle's `VERSION` matches the operator's `monctl_ctl --version`. A truncated or tampered tarball can `docker load` an attacker-supplied image.
- **Fix sketch**: Add `MANIFEST.sha256` to `create_bundle` listing every file's SHA-256, verify in `load_bundle` before extraction. Reject mismatches with a clear error. Cosign signing remains optional.

### M-INST-015 — `extractall()` is vulnerable to tar-slip pre-Python 3.12
- **Severity**: MED
- **File**: `packages/installer/src/monctl_installer/commands/bundle.py:137`
- **Description**: `tarfile.open(path, "r:gz")` + `tf.extractall(work)` without `filter='data'` is the historic CVE-2007-4559 pattern: a tarball entry with `../../../etc/passwd` paths writes arbitrary files. Python 3.12 added `filter` defaults; CLAUDE.md says runtime is Python 3.11.
- **Fix sketch**: Pass `filter='data'` (3.12+) or use a manual safe-extract loop that rejects absolute paths and `..` segments.

---

## Multi-version rolling deploy

### M-CEN-016 — Rollup chain regressed: shared try block per cycle, contradicts memory
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/scheduler/tasks.py:603-610, 622-634`
- **Description**: Per memory `project_rollup_chain_fragility`: "each rollup now has its own try block." Code shows ONE shared try block per cycle: if `_hourly_rollup()` (interface) raises, `_perf_hourly_rollup` and `_avail_hourly_rollup` are skipped for the entire hour. Same for daily. Either the fix never landed or was reverted.
- **Fix sketch**: Split into 3 separate try/except per cycle. Memory may also need updating to reflect actual state if intentional.

### M-CEN-017 — Central can talk to old collector (WS auth) but new collector can't authenticate to old central
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/ws/router.py:31-49`; `packages/collector/src/monctl_collector/central/ws_client.py:77`
- **Description**: Central accepts both `Authorization: Bearer` header (new) and `?token=` query param (old) for WS. New collectors emit only the header. During a rolling upgrade where a new collector connects to an old central (worker upgraded before central), the old central reads the query param and rejects header-only auth.
- **Fix sketch**: For the upgrade path documented in `monctl_ctl upgrade` (canary central → rest centrals → collectors), this works because centrals roll first. Document the constraint loudly in `docs/UPGRADE.md` so operators know not to upgrade collectors first. Long-term, drop the query-param fallback now that the deprecation has shipped.

---

## Deploy / topology

### M-INST-018 — `add-host` for non-leaf roles raises but `remove-host` requires `--force` only
- **Severity**: LOW
- **File**: `packages/installer/src/monctl_installer/commands/topology.py:67-73, 171-177`
- **Description**: Asymmetric guardrails: `add-host` flat-out refuses non-leaf roles, but `remove-host --force` proceeds with no upstream-deregistration check. An operator removing a Patroni node without first stopping it from etcd's perspective leaves a zombie member voting on quorum.
- **Fix sketch**: When `force=True` and roles include `postgres`/`etcd`/`clickhouse`, print a Rich warning listing exact deregistration commands the operator must have run (Patroni `DELETE /cluster/members/<n>`, etcd `member remove <id>`, CH `SYSTEM DROP REPLICA`). Make the operator type a confirmation phrase.

### M-INST-019 — `--remove-orphans` not used by HA-aware projects when shrinking topology
- **Severity**: LOW
- **File**: `packages/installer/src/monctl_installer/commands/deploy.py:124, topology.py:193`
- **Description**: `_apply_project` does run `docker compose up -d --remove-orphans` (good — addresses memory `feedback_compose_orphan_cleanup`). But `remove-host` only runs `docker compose down --remove-orphans` on the **victim** host — it does NOT re-deploy other hosts to remove references. If the removed host had `central` and the inventory `MONCTL_PATRONI_NODES` CSV lists it, surviving centrals still pin it in env until next `monctl_ctl deploy`.
- **Fix sketch**: After `remove-host`, automatically run `deploy()` against the remaining hosts so the node list shrinks consistently.
