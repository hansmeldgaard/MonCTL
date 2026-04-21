# F-X-010 — TLS/SSL call-site audit

**Date:** 2026-04-21
**Scope:** Every production runtime HTTPS/WSS/SSL call site. Dev scripts and tests enumerated separately.

## Summary

- **No silent TLS disabling in production runtime code.** Every call site that disables certificate verification is gated behind a named environment variable (`MONCTL_VERIFY_SSL`, `MONCTL_PUSH_VERIFY_SSL`) with a safe default.
- **Central** uses `httpx`/`aiohttp` defaults (`verify=True`) on all outbound HTTPS. Internal hops (Patroni, etcd, docker-stats sidecar) are plain HTTP on a private bridge network, so TLS is not in scope.
- **Collector** plumbs `verify_ssl: bool = True` through every outbound client class; env override `MONCTL_VERIFY_SSL=false` is the only way to disable it. Dev compose sets `false`; prod compose defaults `true`.
- **docker-stats sidecar** (`docker/docker-stats-server.py`) was defaulting `PUSH_VERIFY_SSL=false` in the Python code. Flipped to `true` as part of this audit; both compose files that deploy it (`docker-compose.collector-prod.yml` + `/opt/monctl/docker-stats/docker-compose.yml`) already set the env explicitly so there is no runtime behaviour change on existing fleets.

## Call-site inventory

### Central (outbound)

| File                                                                   | Line                         | Client                                        | verify       | Notes                                      |
| ---------------------------------------------------------------------- | ---------------------------- | --------------------------------------------- | ------------ | ------------------------------------------ |
| `alerting/notifier.py`                                                 | 52                           | `httpx.AsyncClient`                           | default=True | Outbound webhooks                          |
| `scheduler/tasks.py`                                                   | 319, 358, 1165, 1173         | `httpx.AsyncClient`                           | default=True | Internal/external, depends on URL          |
| `system/router.py`                                                     | 325, 431, 1634, 2360         | `httpx.AsyncClient`                           | default=True | Patroni REST (http://) + health pings      |
| `upgrades/os_service.py`, `os_inventory.py`, `router.py`, `service.py` | various                      | `httpx.AsyncClient` / `aiohttp.ClientSession` | default=True | Sidecar (http://) + external package feeds |
| `docker_infra/router.py`                                               | 137, 192, 218, 254, 285, 306 | `httpx.AsyncClient`                           | default=True | Central sidecar (http://, private bridge)  |
| `python_modules/pypi_client.py`                                        | 26, 43, 58                   | `httpx.AsyncClient(transport=…)`              | default=True | PyPI upstream (https://)                   |

### Collector (outbound)

| File                                          | Env gate                                       | Default | Propagation                                |
| --------------------------------------------- | ---------------------------------------------- | ------- | ------------------------------------------ | ------- |
| `config.py`                                   | `MONCTL_VERIFY_SSL` (env) / `VERIFY_SSL` (env) | `True`  | Single source of truth                     |
| `central/api_client.py`                       | `verify_ssl` param                             | `True`  | `aiohttp.TCPConnector(ssl=verify_ssl)`     |
| `central/ws_client.py`                        | `verify_ssl` param                             | `True`  | `aiohttp.ClientSession.ws_connect(ssl=None | False)` |
| `forward/forwarder.py`                        | `cfg.verify_ssl`                               | `True`  | `aiohttp.TCPConnector`                     |
| `os_update_agent.py`, `upgrade_agent.py`      | `verify_ssl` param                             | `True`  | `aiohttp.TCPConnector`                     |
| `entrypoints/cache_node.py`, `poll_worker.py` | `cfg.central.verify_ssl`                       | `True`  | Plumbs to all clients                      |

### Sidecar (outbound)

| File                               | Env gate                 | Default                       | Notes                                                                                 |
| ---------------------------------- | ------------------------ | ----------------------------- | ------------------------------------------------------------------------------------- |
| `docker/docker-stats-server.py:36` | `MONCTL_PUSH_VERIFY_SSL` | **`true` (as of this audit)** | Compose files explicitly set `false` because they push to the self-signed HAProxy VIP |

## Compose defaults

| File                                                                     | `MONCTL_VERIFY_SSL`   | `MONCTL_PUSH_VERIFY_SSL`           |
| ------------------------------------------------------------------------ | --------------------- | ---------------------------------- |
| `docker/docker-compose.yml` (dev)                                        | `"false"`             | n/a                                |
| `docker/docker-compose.collector.yml`                                    | `${VERIFY_SSL:-true}` | n/a                                |
| `docker/docker-compose.collector-prod.yml`                               | `${VERIFY_SSL:-true}` | `"false"`                          |
| `/opt/monctl/docker-stats/docker-compose.yml` (central hosts, on-server) | n/a                   | `${MONCTL_PUSH_VERIFY_SSL:-false}` |

## Non-runtime (not production, not gating required)

`scripts/generate_packs.py`, `scripts/e2e_smoke.py`, `scripts/seed_devices.py`, `scripts/seed_simulator.py`, `tests/integration/conftest.py`, `tests/integration/test_e2e_smoke.py` — all hardcoded `verify=False`. These targets are local dev environments or the self-signed HAProxy VIP. No action required.

`docs/action-development-guide.md:193` — example code. Added an inline warning comment as part of this audit.

## Deferred

A proper CA bundle for the internal HAProxy VIP would let `MONCTL_PUSH_VERIFY_SSL=true` roll out fleet-wide. That is an ops task (cert issuance + bundle distribution), not a code change, and is out of scope for this audit.
