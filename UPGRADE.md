# Upgrading MonCTL

Most MonCTL upgrades are a tag bump + container restart. Database schema migrations run automatically inside `central-entrypoint.sh` on boot (with an advisory lock to deduplicate concurrent runs across HA central nodes).

## TL;DR

```bash
monctl_ctl upgrade v1.1.0
```

`upgrade` does this in order:

1. Fetches a state snapshot from every host.
2. Picks a canary (first central by default, or `--canary <hostname>`).
3. Renders the canary's compose with the new tag, `scp`'s, `docker compose pull && up -d`.
4. Polls `/v1/health` on the canary until it returns 200 (up to 120 s).
5. Rolls the remaining central hosts sequentially, waiting for each to become healthy.
6. Rolls collectors in parallel.
7. Leaves postgres / etcd / redis / clickhouse compose stacks alone **unless their rendered content changed** (e.g. because you also bumped `CLICKHOUSE_PASSWORD`).

If the canary doesn't come up healthy, the rollout aborts. The other hosts stay on the old tag. You can roll back by re-running `upgrade` with the previous version.

## Before you upgrade

### Always

- Read the release notes for every version between your current and target. Example: upgrading `v1.0.3 → v1.2.0` means you also need to read the `v1.1.0` notes.
- Tag a checkpoint backup of the Postgres database and a ClickHouse backup of the `monctl` database (see below).
- Run `monctl_ctl status` and confirm every subsystem is green. Don't stack an upgrade on top of a sick cluster.

### For major versions

- Read the full per-version notes section below.
- Do it during a scheduled maintenance window — even with rolling restart, browser sessions may need a fresh login after HAProxy rotates through.

## Backup recipes

### Postgres

```bash
# HA setup — run on any central host
docker exec patroni pg_dump -U monctl -d monctl -F c -f /tmp/monctl-$(date +%F).pgdump
docker cp patroni:/tmp/monctl-$(date +%F).pgdump ./

# Standalone — container name is `postgres`
docker exec postgres pg_dump -U monctl -d monctl -F c > monctl-$(date +%F).pgdump
```

### ClickHouse

```bash
# Per-CH node; the BACKUP statement is cluster-aware in recent versions.
docker exec clickhouse clickhouse-client \
  --password "$CLICKHOUSE_PASSWORD" \
  --query "BACKUP DATABASE monctl TO Disk('backups', 'monctl-$(date +%F).zip')"
```

### Secrets

`secrets.env` on the operator machine is the source of truth. If you lose it, there is no path to decrypt the credential store or sign new JWTs. **Back it up to a password manager or hardware vault before the first deploy.** Re-running `monctl_ctl init --force` generates a new `MONCTL_ENCRYPTION_KEY`, which invalidates every at-rest-encrypted credential.

## Rolling back

If a post-upgrade sanity check fails and you want to go back:

```bash
monctl_ctl upgrade v1.0.3   # whatever you came from
```

Rollbacks work as long as Alembic migrations are _forward-compatible_ with the older central image — typically true for minor versions. Major-version bumps may include schema changes the old image can't read; in that case, restore from the pg_dump first.

## Per-version notes

### v1.0.x → v1.1.x (future)

Placeholder — fill when v1.1.0 ships.

### First install (v1.0.0)

`monctl_ctl init` generates fresh secrets and seeds the admin user from `MONCTL_ADMIN_PASSWORD`. There is nothing to upgrade.

## Semver promise

- **Major** (`vN.0.0`) — breaking changes to the REST API, `inventory.yaml` schema, or on-disk state. Requires a read of these notes + backups.
- **Minor** (`v1.N.0`) — new features, new config keys (opt-in). Safe to upgrade straight through.
- **Patch** (`v1.0.N`) — bug fixes only. No inventory or env changes. Always safe.

The installer version must match the image tag: `monctl_ctl v1.2.0` installs images at `v1.2.0`. Mix-and-matching is not supported — `pipx upgrade monctl-installer` first, then `monctl_ctl upgrade v1.2.0`.
