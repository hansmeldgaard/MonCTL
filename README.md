# MonCTL — Distributed Monitoring Platform

MonCTL is a distributed monitoring platform with a central management server and distributed collector nodes. Collectors pull job assignments from central, execute monitoring checks (ping, port, SNMP, HTTP, custom apps), and forward results back for storage, alerting, and configuration tracking.

## Architecture

```
Browser → HAProxy (VIP :443) → central1-4 (:8443)
                                  ├── PostgreSQL (Patroni HA)
                                  ├── ClickHouse (replicated cluster)
                                  └── Redis

Collectors (worker1-4) → poll jobs from central → execute checks → forward results
```

## Tech Stack

| Layer         | Technology                                                                  |
| ------------- | --------------------------------------------------------------------------- |
| Backend       | Python 3.11, FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic 2             |
| Frontend      | React 19, TypeScript 5.9, Vite 7, Tailwind CSS v4, React Query (TanStack) 5 |
| Time-series   | ClickHouse (ReplicatedMergeTree, replicated cluster)                        |
| Relational DB | PostgreSQL 16 (Patroni HA)                                                  |
| Cache         | Redis                                                                       |
| Proxy         | HAProxy (TLS termination, round-robin) + Keepalived (VIP failover)          |
| Collector     | Python 3.12, gRPC (peer communication), SQLite (local buffer)               |
| Icons         | Lucide React                                                                |
| Charts        | Recharts                                                                    |
| Analytics     | Grafana OSS 11.4 (ClickHouse datasource)                                    |
| Code editor   | CodeMirror 6 (Python syntax)                                                |

## Package Structure

```
packages/
  central/          Central management server (FastAPI + React SPA)
  collector/        Distributed collector node
  common/           Shared utilities
  sdk/              SDK package (base classes, testing utilities)
apps/               Built-in monitoring apps (ping, port, HTTP, SNMP)
docker/             Dockerfiles and deployment configs
docker/grafana/     Grafana provisioning (datasources, dashboards)
```

## Central Server

The central server provides:

- **Device management** with CRUD, bulk operations, grouping, and templates
- **App framework** for monitoring checks (built-in + custom) with version management
- **Connector system** for protocol-specific communication (SNMP, SSH, etc.)
- **Collector management** with registration, approval, group assignment, and load balancing
- **Credential vault** with AES-256-GCM encryption and resolution chain
- **Alerting engine** with DSL expressions, threshold variables (4-level override hierarchy), custom units, and event policies
- **Multi-tenant support** with role-based access control (custom RBAC roles)
- **Time-series storage** in ClickHouse with configurable retention
- **Config change tracking** with write suppression, changelog, and diff UI
- **Interface monitoring** with targeted polling, rate calculation, and multi-tier retention
- **Monitoring packs** for import/export of apps, connectors, and alert definitions
- **Python module registry** with PyPI import and wheel distribution
- **Docker infrastructure monitoring** (containers, logs, events, images)
- **Operational dashboard** with aggregated health summary, device status, and performance top-N
- **Grafana integration** with ClickHouse datasource, pre-built dashboards, and analytics page
- **REST API** with JWT cookie auth (web UI) and bearer token auth (collectors/management)

### API

- Web API: `/v1/` — 30 routers (devices, collectors, apps, credentials, alerts, dashboard, config history, etc.)
- Collector API: `/api/v1/` (job pull, result submission, app/connector code, credentials)

### ClickHouse Tables

| Table                  | Purpose                                           |
| ---------------------- | ------------------------------------------------- |
| `availability_latency` | Ping/port/HTTP check results                      |
| `performance`          | Custom metric results (CPU, memory, disk, etc.)   |
| `interface`            | Per-interface SNMP data with hourly/daily rollups |
| `config`               | Configuration tracking (change-only writes)       |
| `alert_log`            | Alert fire/clear history                          |
| `events`               | Event lifecycle (active/ack/cleared)              |

Each table has a `*_latest` materialized view (ReplacingMergeTree) for instant latest-per-key lookups.

## Collector

Each collector node runs three services:

| Service       | Purpose                                                                       |
| ------------- | ----------------------------------------------------------------------------- |
| `cache-node`  | Cluster brain — gossip membership, distributed cache, gRPC peer communication |
| `poll-worker` | Pulls job assignments, executes checks, manages app virtualenvs               |
| `forwarder`   | Batches and ships results to central                                          |

## Deployment

### Prerequisites

- Docker and Docker Compose on all nodes
- SSH access between build machine and servers

### Build & Deploy Central

```bash
# Build (includes frontend)
docker build --platform linux/amd64 --no-cache -t monctl-central:latest \
  -f docker/Dockerfile.central .

# Distribute to central nodes
docker save monctl-central:latest | ssh monctl@<central-ip> 'docker load'

# Start/restart (central2-4)
ssh monctl@<central-ip> 'cd /opt/monctl/central && docker compose down && docker compose up -d'

# Start/restart (central1 — uses central-ha with Patroni)
ssh monctl@10.145.210.41 'cd /opt/monctl/central-ha && docker compose down && docker compose up -d'
```

### Build & Deploy Collector

```bash
# Build
docker build --platform linux/amd64 --no-cache -t monctl-collector:latest \
  -f docker/Dockerfile.collector-v2 .

# Distribute to workers
docker save monctl-collector:latest | ssh monctl@<worker-ip> 'docker load'

# Start/restart
ssh monctl@<worker-ip> 'cd /opt/monctl/collector && docker compose down && docker compose up -d'
```

### Configuration

Central is configured via environment variables with the `MONCTL_` prefix. Key settings:

| Variable                 | Description                                |
| ------------------------ | ------------------------------------------ |
| `MONCTL_DATABASE_URL`    | PostgreSQL connection string               |
| `MONCTL_CLICKHOUSE_HOST` | ClickHouse host                            |
| `MONCTL_REDIS_URL`       | Redis connection string                    |
| `MONCTL_ADMIN_USERNAME`  | Initial admin username (default: `admin`)  |
| `MONCTL_ADMIN_PASSWORD`  | Initial admin password (set on first boot) |
| `MONCTL_JWT_SECRET`      | JWT signing secret                         |

Collectors are configured via `.env` at `/opt/monctl/collector/.env`:

| Variable          | Description                               |
| ----------------- | ----------------------------------------- |
| `NODE_ID`         | Unique node identifier                    |
| `CENTRAL_URL`     | Central server URL                        |
| `CENTRAL_API_KEY` | API key (set after registration)          |
| `PEERS`           | Comma-separated peer addresses for gossip |

## Development

```bash
# Install dev dependencies
cd packages/central && pip install -e ".[dev]"
cd packages/collector && pip install -e ".[dev]"

# Lint
ruff check .
```

## License

Proprietary. All rights reserved.
