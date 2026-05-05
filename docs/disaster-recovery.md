# Disaster Recovery Runbooks

This file is for the 3 a.m. incident operator. Diagnosis lives in
[`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) — once you know the
failure mode, come here for the actual recovery procedure.

Five runbooks, each ending with a `monctl_ctl status` verify step:

1. [Central node lost](#runbook-1--central-node-lost)
2. [Patroni split-brain / etcd stale leader](#runbook-2--patroni-split-brain--etcd-stale-leader)
3. [ClickHouse replica wiped](#runbook-3--clickhouse-replica-wiped)
4. [Redis Sentinel quorum corrupt](#runbook-4--redis-sentinel-quorum-corrupt)
5. [Total cluster loss — restore from backups](#runbook-5--total-cluster-loss--restore-from-backups)

## Before you start

Three rules that apply to every runbook on this page. Read them once
before you skip to your scenario.

1. **Snapshot first, recover second.** If the host is reachable at all,
   take a copy of the data volume before you touch it: `docker run --rm
-v <volume>:/src -v $(pwd):/dst alpine tar -czf /dst/<volume>-$(date
+%FT%H%M).tgz -C /src .`. A failed recovery on a destroyed snapshot
   is unrecoverable; with a snapshot you get a second attempt.
2. **Confirm scope before acting.** A "central is down" page can mean
   one node or four. Run `monctl_ctl status` first; if HA is intact (3
   of 4 central nodes green) the right move is single-node recovery,
   not cluster-wide. Cluster-wide procedures on a partial failure
   make the failure total.
3. **One recovery action at a time.** Apply one step, wait for it to
   converge (Patroni leader election ≈ 30s, ClickHouse replica catch-up
   minutes-to-hours depending on volume), then `monctl_ctl status`. If
   you stack actions you can't tell which one fixed it or which one
   broke something else.

If you can't reach `secrets.env` on the operator laptop, **stop and
read [Runbook 5](#runbook-5--total-cluster-loss--restore-from-backups)
first**. Without `MONCTL_ENCRYPTION_KEY` you can't decrypt the credential
store; some recovery actions require it.

---

## Runbook 1 — Central node lost

**When to use:** One central node is unreachable (hardware failure,
hypervisor crash, VM destroyed). The other 3 nodes report green in
`monctl_ctl status`. HA quorum is intact.

**Don't use this if:** Two or more central nodes are down — see
[Runbook 5](#runbook-5--total-cluster-loss--restore-from-backups).

### Recovery

1. Provision a fresh host with the same hostname and IP as the lost
   node (DNS / `/etc/hosts` for `monctl-centralN` must match the old
   record — ClickHouse and Patroni both rely on hostname identity for
   replica resolution).
2. Set up the host per [`docs/collector-deployment-guide.md`](collector-deployment-guide.md)
   §1–§3 (Docker, `monctl` user, SSH key from operator laptop). For a
   central node also confirm the cluster-internal ports (5432, 5433,
   8008, 2379-2380, 6379, 26379, 8123, 9000, 9181, 9234) are open in
   your firewall — see [`INSTALL.md`](../INSTALL.md) "Firewall / ports".
3. From the operator laptop:

   ```bash
   monctl_ctl preflight --host <hostname>     # confirms SSH, Docker, time-sync, ports
   monctl_ctl deploy --host <hostname>        # renders compose, pushes image, starts services
   ```

4. Watch the rejoin:
   - **Patroni**: `curl http://<hostname>:8008/cluster | jq '.members[] | {name, state, role}'`
     — the new node will appear as `state: creating replica` for a few
     minutes (`pg_basebackup` from the leader), then flip to `state:
running, role: replica`.
   - **ClickHouse**: `_drop_stale_replicas()` in `clickhouse.py` runs at
     central startup and clears any old Keeper metadata for this host
     before re-registering. Watch `docker logs central` for
     `ch_replica_stale_dropped` followed by `ch_replica_registered`.
   - **Redis Sentinel**: a 3-sentinel quorum (central1-3) tolerates one
     missing sentinel; the rebuilt node rejoins on its own. Confirm with
     `docker exec redis-sentinel redis-cli -p 26379 sentinel master mymaster`.

### Verify

```bash
monctl_ctl status                                # all 4 central rows green
ssh monctl@<hostname> 'docker exec patroni curl -s localhost:8008/cluster | jq'
ssh monctl@<hostname> 'docker exec clickhouse clickhouse-client -q "SELECT replica_name, is_leader FROM system.replicas WHERE table = '\''availability_latency_local'\''"'
```

### Common gotchas

- **`/etc/hosts` cross-references** — both ClickHouse nodes need each
  other's hostname → IP mapping in `/etc/hosts` (replication uses
  hostnames internally even when the cluster config uses IPs). If the
  rebuilt node logs `DNS_ERROR: Not found address of host`, populate
  `/etc/hosts` and restart ClickHouse.
- **Redis Sentinel `announce-ip`** — the Docker bridge IP (`172.x.x.x`)
  is what gets advertised by default and unreachable cross-host. The
  installer template sets `announce-ip` to the host IP; if you see
  Sentinel reporting `172.x.x.x` peers, the template hasn't been
  re-rendered — `monctl_ctl deploy --host <hostname>` again.

---

## Runbook 2 — Patroni split-brain / etcd stale leader

**When to use:** `monctl_ctl status` shows `patroni: down` on multiple
hosts, or `curl http://<pg-host>:8008/cluster` shows multiple members
with `role: leader`, or all members with `state: stop`. The most common
trigger is etcd losing quorum during a network partition and recovering
with a stale leader key.

### Pre-flight

1. **Identify the canonical leader.** Inspect every member:

   ```bash
   for h in central1 central2 central3; do
     echo "=== $h ==="
     ssh monctl@$h 'curl -s http://localhost:8008/patroni | jq "{state, role, xlog: .xlog.location, timeline}"'
   done
   ```

   The member with the highest `xlog.location` (last WAL byte written)
   wins. Mark it; it's the only member that should keep its data.

2. **Snapshot the leader's pgdata** before doing anything else:

   ```bash
   ssh monctl@<leader-host> 'docker exec patroni tar -czf /tmp/pgdata-snap-$(date +%FT%H%M).tgz /var/lib/postgresql/data'
   ssh monctl@<leader-host> 'docker cp patroni:/tmp/pgdata-snap-*.tgz /opt/monctl/'
   ```

### Reset etcd

```bash
# Stop all 3 etcd containers SIMULTANEOUSLY (they form a quorum; restarting
# one at a time keeps the stale state alive).
for h in central1 central2 central3; do ssh monctl@$h 'docker stop etcd' & done
wait

# Remove the Patroni leader key on every member.
for h in central1 central2 central3; do
  ssh monctl@$h 'docker run --rm -v etcd-data:/data alpine sh -c "rm -rf /data/member"'
done

# Restart all 3 etcd containers, again simultaneously.
for h in central1 central2 central3; do ssh monctl@$h 'docker start etcd' & done
wait
```

### Force Patroni re-election

```bash
# Stop every Patroni container.
for h in central1 central2 central3; do ssh monctl@$h 'docker stop patroni' & done
wait

# Start the canonical leader FIRST. Wait for `state: running, role: leader`
# in `curl http://<leader>:8008/cluster | jq` (≈30s).
ssh monctl@<leader-host> 'docker start patroni'

# Then start the other two as replicas. They'll re-init via pg_basebackup
# from the leader if their data has diverged.
for h in <replica-host-1> <replica-host-2>; do ssh monctl@$h 'docker start patroni' & done
wait
```

If a replica refuses to rejoin (`state: stop` after 5 min of retries),
force re-init from the leader:

```bash
ssh monctl@<replica-host> '
  docker exec patroni patronictl reinit monctl-cluster <replica-host>
'
```

`patronictl reinit` blows away the replica's pgdata and re-runs
`pg_basebackup`. Only do this on a member you've already confirmed is
not the canonical leader.

### Verify

```bash
monctl_ctl status                                       # all 3 patroni rows green
curl -s http://<any-pg-host>:8008/cluster | jq '.members[] | {name, state, role, lag: .lag}'
# Expected: exactly one role=leader, others role=replica, lag=0 (or seconds, not minutes).
```

---

## Runbook 3 — ClickHouse replica wiped

**When to use:** A ClickHouse node was destroyed and rebuilt, or its
data volume was deleted. `monctl_ctl status` reports
`clickhouse: degraded` and the surviving node logs
`Replica /clickhouse/tables/.../<wiped-replica> already exists in
ZooKeeper`.

### What's automated

`_drop_stale_replicas()` in
`packages/central/src/monctl_central/storage/clickhouse.py` runs at
every central startup. It walks `system.replicas` on every CH peer,
identifies any replica that's missing its Keeper metadata, drops the
stale entry via `SYSTEM DROP REPLICA <name>`, and re-runs `CREATE
TABLE ON CLUSTER` so the cluster recreates the missing tables on the
rebuilt node. **In most cases you do nothing — just `monctl_ctl deploy`
the central image and the auto-cleanup runs on the next central
restart.**

The remaining manual cases:

- The auto-cleanup skips a replica whose hostname doesn't resolve. Fix
  `/etc/hosts` cross-references (see Runbook 1) and try again.
- The Keeper itself is wedged — see "Keeper quorum lost" in
  [`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md).

### Manual fallback

If the auto-cleanup didn't run (e.g. you can't restart central, or
there's no central node to run the cleanup from), drop the stale
replica by hand from any healthy CH node:

```bash
ssh monctl@<healthy-ch-host>
docker exec clickhouse clickhouse-client --password "$CLICKHOUSE_PASSWORD" \
  --query "SYSTEM DROP REPLICA '<wiped-host>' FROM ZKPATH '/clickhouse/tables/<shard>/<database>/<table>'"
```

Run the `SYSTEM DROP REPLICA` for every replicated table that lists the
dead host. List them with:

```sql
SELECT zookeeper_path, replica_name FROM system.replicas WHERE replica_name = '<wiped-host>';
```

Then re-run `monctl_ctl deploy --host <wiped-host>` to re-register the
node — `_drop_stale_replicas` won't do anything (you've already
cleaned up) but `ensure_tables()` will recreate every replicated
table on the rebuilt node and replication will catch up.

### Verify

```bash
monctl_ctl status                                                       # clickhouse green
ssh monctl@<wiped-host> 'docker exec clickhouse clickhouse-client -q "SELECT count() FROM system.replicas WHERE is_readonly OR is_session_expired"'
# Expected: 0
ssh monctl@<wiped-host> 'docker exec clickhouse clickhouse-client -q "SELECT replica_name, is_leader, absolute_delay FROM system.replicas WHERE table = '\''availability_latency_local'\''"'
# Expected: absolute_delay drops from minutes/hours to seconds as the rebuilt replica catches up.
```

### Memory pressure note

If you see OOM kills on the CH container during catch-up, the
default `mem_limit` is too tight — replication can spike memory while
the rebuilt node ingests its backlog. Both CH nodes were upgraded to
8 GB RAM in 2026-03-31 specifically to prevent the OOM→queue
growth→OOM spiral.

---

## Runbook 4 — Redis Sentinel quorum corrupt

**When to use:** `monctl_ctl status` shows `redis: degraded` and
multiple Sentinels disagree about the master, or the master flips
back and forth every few seconds (split-brain), or Sentinel logs show
peers at `172.x.x.x` instead of `10.x.x.x` host IPs.

### Why this happens

Sentinel modifies its own config file at runtime (it persists the
discovered master / replica peers). A Docker container restart
reloads the modified file, which can preserve stale state from a
previous topology — including peer IPs that resolve to long-dead
container IPs. The fix is a **simultaneous** restart of all 3
Sentinels so none of them comes back believing the others' stale
state is authoritative.

### Recovery

1. Verify `announce-ip` is correct in every Sentinel config. If it's
   set to `172.x.x.x` or unset, the templates haven't been rendered
   for this topology — re-run `monctl_ctl deploy` on each central
   host before continuing.

   ```bash
   for h in central1 central2 central3; do
     echo "=== $h ==="
     ssh monctl@$h 'docker exec redis-sentinel cat /tmp/sentinel.conf | grep announce-ip'
   done
   ```

   Expected: each one prints the host IP (`10.145.x.x`), not a Docker
   bridge IP.

2. Coordinated restart (must be simultaneous — see "Why this happens"
   above):

   ```bash
   for h in central1 central2 central3; do ssh monctl@$h 'docker stop redis-sentinel' & done
   wait
   for h in central1 central2 central3; do ssh monctl@$h 'docker start redis-sentinel' & done
   wait
   ```

3. Wait 30s for re-discovery, then check the master from each
   Sentinel:

   ```bash
   for h in central1 central2 central3; do
     echo "=== $h ==="
     ssh monctl@$h 'docker exec redis-sentinel redis-cli -p 26379 sentinel master mymaster | head -20'
   done
   ```

   All three should agree on the same `ip` and `port` for the master.
   `num-other-sentinels: 2` confirms quorum.

### Verify

```bash
monctl_ctl status                                          # redis green
ssh monctl@<central1> 'docker exec redis redis-cli ROLE'   # master | replica
# Application probe — central reads/writes through the sentinel-aware client:
curl -sk https://<vip>/v1/system/health | jq '.subsystems.redis'
```

---

## Runbook 5 — Total cluster loss — restore from backups

**When to use:** All central nodes are unreachable / destroyed. You're
rebuilding the cluster from scratch and need to restore the data, or
HA quorum has been lost in both Patroni and ClickHouse simultaneously
and the surviving members are unrecoverable.

### Pre-flight — what you must have

Without these, you can't restore:

| Artifact         | Source                             | Why                                                                                                                                                                                              |
| ---------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `secrets.env`    | Operator laptop / vault            | Contains `MONCTL_ENCRYPTION_KEY` — without it, every encrypted credential in PG is unrecoverable. **No path to recover this** if lost; rotate every monitored device's credential after restore. |
| Latest pg_dump   | Wherever your nightly backup lives | The PostgreSQL state (devices, apps, alerts, users, credentials in encrypted form).                                                                                                              |
| Latest CH backup | ClickHouse `BACKUP` artefact       | All time-series data. Lossy: anything since the last backup is gone.                                                                                                                             |
| `inventory.yaml` | Operator laptop                    | Describes the cluster topology — the installer renders compose / .env from this.                                                                                                                 |

If `secrets.env` is lost, **stop and decide first** whether to:

- **Rotate everything**: re-init the cluster with a fresh
  `MONCTL_ENCRYPTION_KEY`, restore PG schema only (drop the encrypted
  credential payloads), have operators re-enter every device
  credential. CH data is unaffected.
- **Accept partial recovery**: restore the cluster but mark every
  encrypted credential as broken. Useful only if the credential
  set is small enough to manually re-enter without a maintenance
  window.

There's no third option — `MONCTL_ENCRYPTION_KEY` is symmetric and
not recoverable from anything else.

### Restore

1. Provision new central / collector hosts per [`INSTALL.md`](../INSTALL.md).
2. Restore `secrets.env` to the operator laptop (or generate fresh
   secrets via `monctl_ctl init` if you've decided to rotate).
3. `monctl_ctl deploy` to bring up empty central nodes. **Don't deploy
   collectors yet** — they'd register against an empty central and the
   collector_id assignment would conflict with the restored PG state.
4. Restore Postgres on the active leader:

   ```bash
   ssh monctl@<central1>
   docker cp ~/monctl-YYYY-MM-DD.pgdump patroni:/tmp/
   docker exec patroni pg_restore -U monctl -d monctl --clean --if-exists /tmp/monctl-YYYY-MM-DD.pgdump
   ```

   Patroni replicates this to the other members automatically — no
   restore needed on replicas.

5. Restore ClickHouse on every CH node (the `BACKUP` from `UPGRADE.md`
   is per-node, not cluster-aware in older CH versions; check your CH
   version):

   ```bash
   for h in <ch-host-1> <ch-host-2>; do
     ssh monctl@$h "docker cp /opt/monctl/backups/monctl-YYYY-MM-DD.zip clickhouse:/tmp/"
     ssh monctl@$h "docker exec clickhouse clickhouse-client --password '\$CLICKHOUSE_PASSWORD' \\
       --query \"RESTORE DATABASE monctl FROM Disk('backups', 'monctl-YYYY-MM-DD.zip')\""
   done
   ```

6. Restart central app on every node (`docker compose restart central`)
   so it picks up the restored PG state, runs alembic, and registers
   itself with the restored ClickHouse.
7. **Now** deploy collectors:

   ```bash
   monctl_ctl deploy --role collector
   ```

   The Wave 2 register-collectors post-step will mint fresh per-host
   API keys against the restored central.

### Verify

```bash
monctl_ctl status                       # everything green
# Spot-check: log in to UI, confirm device count matches your last
# known-good. Confirm at least one alert fires (the alert engine
# reads from CH — proves the time-series state is back).
```

If credentials were rotated, walk every monitored device and
re-enter its credential before unmuting alerts — otherwise every
SNMP / SSH check fires `error_category="config"` until the operator
catches up.

---

## After every runbook

Whatever you ran, finish with:

1. **`monctl_ctl status`** — every subsystem green.
2. **Patroni**: `curl http://<pg-host>:8008/cluster | jq` — exactly one
   leader, replicas at `lag: 0` (or steadily decreasing).
3. **ClickHouse**: `SELECT count() FROM system.replicas WHERE
is_readonly OR is_session_expired` should return 0 on every CH
   node. `absolute_delay` on `*_local` tables should be small and
   shrinking.
4. **Redis**: `docker exec redis-sentinel redis-cli -p 26379 sentinel
master mymaster | grep num-other-sentinels` should return `2` on
   all 3 sentinel hosts.
5. **Open the UI** and confirm the dashboard renders. The top-bar dot
   should be green (admin-only) and the System Health page should show
   no "degraded" rows.
6. **Write a post-mortem.** What was the trigger, what worked, what
   surprised you. Memory has been wrong before (`project_*.md` notes
   captured at one point in time may not match current code) — if a
   runbook step here misled you, edit the file. The next 3 a.m.
   operator is you.
