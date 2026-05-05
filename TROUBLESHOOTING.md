# Troubleshooting MonCTL

Most problems surface via `monctl_ctl status` or `monctl_ctl validate`. Find your symptom below.

---

## `monctl_ctl validate` failures

### `ssh.reachable fail`

SSH handshake failed. Check in this order:

1. `ssh <user>@<ip>` from the operator host — does it work outside the installer?
2. Is the user in `inventory.yaml` correct? (`ssh.user` field, default `monctl`)
3. Is your public key in `~<user>/.ssh/authorized_keys` on the target?
4. Is port 22 open? Cloud security groups are the usual culprit.

### `docker.installed fail`

Docker Engine isn't running or isn't in PATH. Run on the host:

```bash
systemctl status docker
which docker
```

If Docker isn't installed: Ubuntu/Debian one-liner is `curl -fsSL https://get.docker.com | sh`. Add the SSH user to the `docker` group and re-log.

### `docker.compose_plugin fail`

You have standalone `docker-compose` (the old Python binary), not the plugin. Install:

```bash
# Debian / Ubuntu
apt-get install -y docker-compose-plugin
docker compose version   # verify
```

### `port.NNN fail`

Something is already listening on a port MonCTL needs. Find it:

```bash
ss -tlnp | grep ':NNN'
```

Typical causes: a stray Postgres (port 5432), a pre-existing Redis (6379), a host web server on 443. Stop it, disable the systemd unit, and re-run `validate`.

### `ram.total fail`

The host has less than the minimum RAM recommended for its role set. Either add RAM or move the heaviest role (usually `clickhouse` at 4 GB minimum) to another host.

### `time.synced warn`

NTP isn't in sync. Patroni and ClickHouse replication _require_ synced clocks (skew > 500 ms → failover storms). Fix:

```bash
# Ubuntu / Debian
timedatectl set-ntp true
systemctl restart systemd-timesyncd

# Minutes later
timedatectl status     # must show "System clock synchronized: yes"
```

---

## `monctl_ctl status` shows subsystems as `down`

### `central down` (`HTTP 8443 /v1/health unreachable`)

Central container isn't serving. Log in to the host:

```bash
monctl_ctl ssh <host>
docker ps | grep central
docker logs central --tail 200
```

Common causes:

- **Database URL wrong** — `MONCTL_DATABASE_URL` points at an unreachable Patroni/HAProxy. Re-render with `monctl_ctl deploy`.
- **Alembic migration crashed** — look for `Running upgrade` lines followed by a traceback. Fix the migration (or roll back the image tag) and bounce with `docker compose restart central`.
- **TLS cert missing** — the `tls_certs` named volume is empty. `monctl_ctl deploy` on the `central` host regenerates it.

### `patroni down` / `state=stop`

Leader lost or PG crashed.

```bash
monctl_ctl ssh <pg-host>
docker logs patroni --tail 200
curl http://localhost:8008/cluster | jq
```

- If all members show `state: stop`, etcd probably has a stale leader key — restart all three etcd containers simultaneously, then restart patroni.
- If one member is `state: running, role: leader` and others are `role: replica`, the "leader" is correct; the dead replicas will rejoin on restart.
- **Never `rm -rf` pgdata on a replica without first confirming the leader is healthy.** Replicas auto-rebuild via `pg_basebackup` from the leader — if the leader is also broken you'll lose data.

### `clickhouse down` (`SELECT 1 failed`)

```bash
monctl_ctl ssh <ch-host>
docker logs clickhouse --tail 200
```

Classic problems:

- **Keeper quorum lost** — look for `Cannot connect to Keeper` in logs. Restart all CH nodes carrying `embedded_keeper` simultaneously.
- **Disk full** — ClickHouse stops writing when disk <10% free. `df -h /` on the host; delete old data parts via `TTL` or extend the volume.
- **Replica diverged** — stale replica metadata after a node was gone too long. See _Stale CH replica_ below.

### `redis down` / `redis-cli failed`

If sentinel is configured, Sentinel may have failed over and the container you're probing is now a replica advertising that state. That's fine — `monctl_ctl status` reports `role=replica`, not `down`. If the container itself is down:

```bash
docker logs redis --tail 100
# CLAUDE.md gotcha: sentinel needs announce-ip; verify
docker exec redis-sentinel cat /tmp/sentinel.conf | grep announce-ip
```

If `announce-ip` is wrong or missing, the sentinel config in `/opt/monctl/redis/sentinel.conf` is stale. Re-run `monctl_ctl deploy` on that host.

---

## Upgrade-specific

### `upgrade aborted: canary <host> unhealthy after upgrade`

The canary central started but `/v1/health` didn't return 200 within the timeout. It's almost always an Alembic migration failure. Check:

```bash
monctl_ctl logs <canary> --service central --tail 500
```

If the migration itself is broken, roll back:

```bash
monctl_ctl upgrade <previous-version>
```

If it's a transient (e.g. CH connection timeout during boot), wait a minute and re-run the same upgrade — the `deploy` step is idempotent and the canary will just re-verify.

### `upgrade` appears to hang

Either an Alembic migration is running against a large table (tens of minutes is possible for `ALTER COLUMN` on a busy table) or `/v1/health` is serving degraded. Open a second terminal:

```bash
monctl_ctl ssh <canary>
docker logs central -f --tail 20
```

Watch for `Running upgrade` Alembic lines. Don't Ctrl-C the installer — the advisory lock is held by the central container, not the installer.

---

## Installer (`monctl_ctl`) problems

### `secrets.env has mode 0644; must be 0600`

Someone chmod'd it (often a shared config-management system). Fix:

```bash
chmod 600 secrets.env
```

If this happens repeatedly, your config-management tool is clobbering modes — add an exception.

### `MONCTL_ENCRYPTION_KEY looks like a placeholder`

You're using a hand-edited `secrets.env` with `CHANGEME` still in it. Either fill in real values or regenerate:

```bash
monctl_ctl init --force   # regenerates secrets.env; prints new admin password
```

**Warning:** a new `MONCTL_ENCRYPTION_KEY` invalidates every at-rest-encrypted credential (the device credentials you've configured in MonCTL itself, not the infra passwords). You will need to re-enter those in the UI.

### `deploy precondition failed: secrets.env does not exist`

Run `monctl_ctl init` first. Or, if you have an existing `inventory.yaml`:

```bash
monctl_ctl init --from inventory.yaml --force
```

---

## Where to look next

- Central logs — `monctl_ctl logs <host> --service central --tail 500 --follow`
- Container-level logs — `docker logs <container> --tail 500`
- Cluster health dashboard — browse to `https://<VIP>/system/health`
- Patroni cluster state — `curl http://<pg-host>:8008/cluster`
- ClickHouse replica state — `docker exec clickhouse clickhouse-client --password $CH_PASSWORD --query "SELECT * FROM system.replicas"`

If you've identified the failure mode and now need the recovery
procedure, jump to [`docs/disaster-recovery.md`](docs/disaster-recovery.md)
— five runbooks: central node lost, Patroni split-brain, ClickHouse
replica wiped, Redis Sentinel quorum corrupt, total cluster loss
restore.

Still stuck? Run `monctl_ctl status` and attach the full output to your support ticket. If you're opening a GitHub issue, also attach:

- Redacted `inventory.yaml` (IPs and passwords removed)
- `monctl_ctl --version`
- Central container log for the host that's unhealthy (`docker logs central --tail 1000`)
