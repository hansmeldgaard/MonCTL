# MonCTL Environment Variables

Every `MONCTL_*` env var that central, the collector, the installer, or the
docker-stats sidecar reads at runtime. The customer installer's
`monctl_ctl init` + `monctl_ctl deploy` populate these for you; this doc
exists so an operator debugging by hand has one place to grep.

> Source of truth, when in doubt:
> `packages/central/src/monctl_central/config.py` — the Pydantic settings
> class for central. Other surfaces are documented here from their
> respective `config.py` / `entrypoint.sh` files.

## Conventions

- All env-var names are uppercase with underscores. The `MONCTL_` prefix
  is implicit on every central setting (Pydantic strips it). Where a
  collector or sidecar uses a non-prefixed name, that's called out.
- "Set by installer?" reflects what `monctl_ctl deploy` writes into
  `/opt/monctl/<project>/.env`. A "yes" means the operator doesn't have
  to think about it on customer installs.
- "Default" is the value Pydantic / the entrypoint resolves when the
  variable is unset. Empty string means "feature off / required".

## Central server

### Server / network

| Variable             | Default     | Required? | Set by installer? | Notes                                                                                                                                                                                                |
| -------------------- | ----------- | --------- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `MONCTL_HOST`        | `0.0.0.0`   | no        | no                | Bind address. Customer installs front central with HAProxy on the same host; leave default.                                                                                                          |
| `MONCTL_PORT`        | `8443`      | no        | no                | Internal port central listens on (HTTP, plain). HAProxy terminates TLS at `:443`.                                                                                                                    |
| `MONCTL_DEBUG`       | `false`     | no        | no                | FastAPI debug mode. Don't enable in prod — leaks tracebacks.                                                                                                                                         |
| `MONCTL_LOG_LEVEL`   | `INFO`      | no        | no                | Stdlib root logger level. Set to `DEBUG` for one container at a time when troubleshooting.                                                                                                           |
| `MONCTL_INSTANCE_ID` | (generated) | no        | yes               | Unique per central node. `main.py` lifespan auto-generates on startup if unset. The OS-install lease + scheduler leader election key off this — review #2 R-CEN-004 made empty-string a fatal error. |
| `MONCTL_NODE_NAME`   | `""`        | no        | yes               | Human-readable hostname (e.g. `central1`). Surfaced in system-health UI.                                                                                                                             |
| `MONCTL_ROLE`        | `all`       | no        | yes               | One of `api`, `scheduler`, `all`. Only `scheduler`/`all` instances participate in leader election.                                                                                                   |

### PostgreSQL / Redis / ClickHouse

| Variable                         | Default                                                    | Required?          | Set by installer? | Notes                                                                                                                                 |
| -------------------------------- | ---------------------------------------------------------- | ------------------ | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `MONCTL_DATABASE_URL`            | `postgresql+asyncpg://monctl:monctl@localhost:5432/monctl` | yes (custom value) | yes               | Async SQLAlchemy DSN. HA setups point at `127.0.0.1:5432` (HAProxy fronts the Patroni cluster).                                       |
| `MONCTL_REDIS_URL`               | `redis://localhost:6379/0`                                 | yes (custom value) | yes               | Standalone Redis. Ignored if `MONCTL_REDIS_SENTINEL_HOSTS` is set.                                                                    |
| `MONCTL_REDIS_SENTINEL_HOSTS`    | `""`                                                       | conditional        | yes               | Comma-separated `host:port,host:port,...`. When set, central uses Sentinel discovery — `MONCTL_REDIS_URL` is then unused.             |
| `MONCTL_REDIS_SENTINEL_MASTER`   | `monctl-redis`                                             | no                 | yes               | Master name registered with Sentinel. Must match `redis.conf` / `sentinel.conf`.                                                      |
| `MONCTL_CLICKHOUSE_HOSTS`        | `localhost`                                                | yes (custom value) | yes               | Comma-separated host list for clickhouse-connect failover. Order matters; first reachable wins.                                       |
| `MONCTL_CLICKHOUSE_PORT`         | `8123`                                                     | no                 | yes               | HTTP port. CH native (`9000`) is not used.                                                                                            |
| `MONCTL_CLICKHOUSE_DATABASE`     | `monctl`                                                   | no                 | yes               | Database to use. Created at first startup.                                                                                            |
| `MONCTL_CLICKHOUSE_CLUSTER`      | `monctl_cluster`                                           | no                 | yes               | `ON CLUSTER` name in the DDL. Must match `clickhouse-config.xml`.                                                                     |
| `MONCTL_CLICKHOUSE_USER`         | `default`                                                  | no                 | yes               | Read+write user. Layer-3 row policies (per-tenant scoping) live on a separate `monctl_readonly` user used by Superset (`readonly=2`). |
| `MONCTL_CLICKHOUSE_PASSWORD`     | `""`                                                       | yes                | yes               | Generated by `monctl_ctl init`.                                                                                                       |
| `MONCTL_CLICKHOUSE_ASYNC_INSERT` | `true`                                                     | no                 | no                | Enables CH `async_insert` for the ingest path. Leave on; turning off triples insert latency.                                          |
| `MONCTL_CLICKHOUSE_POOL_SIZE`    | `8`                                                        | no                 | no                | Connections per central node. Bump to 16 if you see `ch_pool_acquire_timeout` log spam.                                               |

### Authentication / encryption / cookies

| Variable                                 | Default | Required?       | Set by installer? | Notes                                                                                                                            |
| ---------------------------------------- | ------- | --------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `MONCTL_ENCRYPTION_KEY`                  | `""`    | **yes**         | yes               | 64-char hex (32 bytes). Encrypts every `Credential.secret_data` row at rest. **Rotation is destructive**; treat as load-bearing. |
| `MONCTL_JWT_SECRET_KEY`                  | `""`    | **yes**         | yes               | 64-char hex. Signs login JWTs + OIDC ID tokens. Rotating logs every user out.                                                    |
| `MONCTL_JWT_ALGORITHM`                   | `HS256` | no              | no                | Symmetric. Don't change.                                                                                                         |
| `MONCTL_JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `30`    | no              | no                | Access-token lifetime.                                                                                                           |
| `MONCTL_JWT_REFRESH_TOKEN_EXPIRE_DAYS`   | `7`     | no              | no                | Refresh-token lifetime.                                                                                                          |
| `MONCTL_COOKIE_SECURE`                   | `true`  | no              | yes               | `Secure` flag on auth cookies. Set to `false` only for dev that serves UI over plain HTTP.                                       |
| `MONCTL_ADMIN_USERNAME`                  | `admin` | no              | no                | First-boot admin account name.                                                                                                   |
| `MONCTL_ADMIN_PASSWORD`                  | `""`    | first-boot only | yes               | Pronounceable password generated by `monctl_ctl init`. Read it from the install output once; never echoed again.                 |

### OAuth2 provider (Superset SSO)

| Variable                     | Default | Required?                        | Set by installer? | Notes                                                                                                                |
| ---------------------------- | ------- | -------------------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------- |
| `MONCTL_OAUTH_CLIENT_ID`     | `""`    | yes (when Superset host present) | yes               | OAuth2 client ID Superset authenticates with.                                                                        |
| `MONCTL_OAUTH_CLIENT_SECRET` | `""`    | yes (same)                       | yes               | OAuth2 client secret.                                                                                                |
| `MONCTL_OAUTH_REDIRECT_URIS` | `""`    | yes (same)                       | yes               | Comma-separated **exact-match** allowed redirect URIs. No wildcards.                                                 |
| `MONCTL_OAUTH_ISSUER`        | `""`    | yes (same)                       | yes               | OIDC issuer claim. Should match the public base URL browsers see (the VIP, or the first central host:8443 fallback). |

### Per-collector auth + tenant scoping

| Variable                            | Default | Required? | Set by installer? | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ----------------------------------- | ------- | --------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `MONCTL_COLLECTOR_API_KEY`          | `""`    | yes       | yes               | Shared bearer secret collectors send on `/api/v1/*` and the WS upgrade. Per-collector keys (PR #120) take precedence when issued.                                                                                                                                                                                                                                                                                                                     |
| `MONCTL_REQUIRE_PER_COLLECTOR_AUTH` | `false` | no        | no                | When `true`, central rejects shared-secret callers that can't be matched to a specific collector. Default `false` until your fleet has fully migrated. Wave 2 (PRs #186/#187/#188) shipped `monctl_ctl deploy`'s register-collectors post-step — once every collector has a per-host key (verify by grepping central logs for `collector_shared_secret_used` and confirming no recent occurrences), set this to `true` to close the S-CEN-002 sunset. |
| `MONCTL_TRUSTED_PROXIES`            | `""`    | no        | yes (prod)        | Comma-separated IP list whose `X-Forwarded-For` central trusts (review #2 S-CEN-009). Fail-closed default — set this to your HAProxy IP(s) on multi-node deploys to keep capturing the original client IP in audit rows.                                                                                                                                                                                                                              |

### Infrastructure topology + health

| Variable                         | Default                         | Required? | Set by installer?   | Notes                                                                                              |
| -------------------------------- | ------------------------------- | --------- | ------------------- | -------------------------------------------------------------------------------------------------- |
| `MONCTL_PATRONI_NODES`           | `""`                            | no        | yes (HA)            | `name:ip,name:ip,...`. Drives `/v1/system/health` Patroni subsystem. Leave empty on standalone PG. |
| `MONCTL_ETCD_NODES`              | `""`                            | no        | yes (HA)            | Same shape; drives etcd subsystem.                                                                 |
| `MONCTL_DOCKER_STATS_HOSTS`      | `""`                            | no        | yes (central nodes) | `label:ip:port,label:ip:port,...` for the central-tier docker-stats sidecars.                      |
| `MONCTL_TLS_SAN_IPS`             | `""`                            | no        | yes                 | Comma-separated extra IPs for the self-signed cert SAN list.                                       |
| `MONCTL_TLS_CERT_PATH`           | `/etc/haproxy/certs/monctl.pem` | no        | yes                 | Where HAProxy reads its cert. Shared volume mount.                                                 |
| `MONCTL_LEADER_LOCK_TTL`         | `30`                            | no        | no                  | Scheduler leader Redis SETNX TTL (seconds). Renewed every 10 s.                                    |
| `MONCTL_STALE_THRESHOLD_SECONDS` | `90`                            | no        | no                  | Heartbeat age above which a collector goes `STALE`.                                                |
| `MONCTL_DEAD_THRESHOLD_SECONDS`  | `300`                           | no        | no                  | Heartbeat age above which a collector goes `DOWN`.                                                 |

### Storage paths + ingestion + alerting

| Variable                       | Default          | Required? | Set by installer? | Notes                                                                                           |
| ------------------------------ | ---------------- | --------- | ----------------- | ----------------------------------------------------------------------------------------------- |
| `MONCTL_WHEEL_STORAGE_DIR`     | `/data/wheels`   | no        | yes               | Where central caches pack-bundled Python wheels. Mount a persistent volume in the compose file. |
| `MONCTL_UPGRADE_STORAGE_DIR`   | `/data/upgrades` | no        | yes               | Where the upgrade subsystem stages package downloads.                                           |
| `MONCTL_INGEST_BATCH_SIZE`     | `1000`           | no        | no                | Max rows per CH insert batch.                                                                   |
| `MONCTL_INGEST_FLUSH_INTERVAL` | `5.0`            | no        | no                | Seconds between forced flushes (if batch hasn't filled).                                        |
| `MONCTL_INGEST_MAX_QUEUE_SIZE` | `50000`          | no        | no                | Backpressure cap on the ingest queue.                                                           |
| `MONCTL_RATE_LIMIT_PER_KEY`    | `100`            | no        | no                | API key rate limit (req/min).                                                                   |
| `MONCTL_INCIDENT_ENGINE`       | `shadow`         | no        | no                | One of `off`, `shadow`. Phase-1 of the event policy rework.                                     |

## Collector

| Variable                            | Default         | Required?   | Set by installer? | Notes                                                                                                                                                                                    |
| ----------------------------------- | --------------- | ----------- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `MONCTL_CENTRAL_URL`                | (none)          | yes         | yes               | `https://<vip>` for HA, or `https://<central1>:8443` standalone.                                                                                                                         |
| `MONCTL_COLLECTOR_API_KEY`          | (none)          | yes         | yes               | Same value central knows; per-collector keys take precedence when bootstrapped via `MONCTL_REGISTRATION_TOKEN`.                                                                          |
| `MONCTL_REGISTRATION_TOKEN`         | (none)          | conditional | no                | One-shot token from `monctl_ctl` to perform first-boot registration and receive a per-collector key.                                                                                     |
| `MONCTL_VERIFY_SSL`                 | `false` (today) | no          | yes               | Whether the collector verifies central's TLS cert. Defaults from `cluster.tls.verify` in inventory: `false` for self-signed (bootstrap), `true` for `provided`.                          |
| `MONCTL_PEER_TOKEN`                 | (none)          | **yes**     | yes               | gRPC bearer between cache-node and poll-worker on the same host. Refusing to start without this is the S-COL-001 fail-safe. Per-host derived from `MONCTL_PEER_TOKEN_SEED` (M-INST-012). |
| `MONCTL_ALLOW_UNAUTHENTICATED_PEER` | `false`         | no          | no                | DEPRECATED escape hatch for legacy deploys without a peer token. Remove once every collector ships one.                                                                                  |
| `MONCTL_INSECURE_TLS`               | `false`         | no          | no                | Repo-wide knob that gates every `verify=False` call site (per F-X-010). Don't enable in prod.                                                                                            |
| `MONCTL_ACCEPT_NEW_HOSTKEYS`        | `false`         | no          | no                | (Installer side, not collector) trust unknown SSH host keys on first contact and persist to `~/.ssh/known_hosts`.                                                                        |

## Customer installer (`monctl_ctl`)

| Variable                     | Default | Required? | Notes                                                                                                                                                                                                   |
| ---------------------------- | ------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `MONCTL_ACCEPT_NEW_HOSTKEYS` | `false` | no        | Per-process toggle equivalent to the `--accept-new-hostkeys` CLI flag. Trust unknown SSH host keys on first contact and write them to `~/.ssh/known_hosts`. Use ONCE during initial cluster onboarding. |

## docker-stats sidecar (per host)

| Variable                 | Default         | Required? | Set by installer? | Notes                                                              |
| ------------------------ | --------------- | --------- | ----------------- | ------------------------------------------------------------------ |
| `MONCTL_PUSH_API_KEY`    | (none)          | yes       | yes               | Same shared collector key — sidecars POST host metrics to central. |
| `MONCTL_PUSH_VERIFY_SSL` | `false` (today) | no        | yes               | Mirrors `MONCTL_VERIFY_SSL` resolution from `cluster.tls.verify`.  |
| `MONCTL_PUSH_LABEL`      | (host name)     | no        | yes               | Identifier under which metrics from this sidecar appear.           |

## Where the installer wires these

The installer's render templates live under
`packages/installer/src/monctl_installer/render/templates/env/*.env.j2`.
A fresh `monctl_ctl deploy` materialises every `${KEY}` placeholder
into per-host `/opt/monctl/<project>/.env` (mode 0600) using values
from `secrets.env` plus per-host derivations (peer token via HMAC,
OAuth issuer from VIP, etc.).

## Adding a new env var

1. Add the field to the matching settings class
   (`packages/central/src/monctl_central/config.py`, the collector's
   `config.py`, etc.).
2. Add a row to this doc under the right section. Required? Default?
   Who sets it?
3. Add a line to the matching `.env.j2` template and to
   `packages/installer/src/monctl_installer/secrets/generator.py` if
   the value should be auto-generated by `init`.
4. If it gates security behaviour, add a Known-pitfall entry to
   `CLAUDE.md` so the next reviewer doesn't miss it.
