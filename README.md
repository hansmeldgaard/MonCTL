# MonCTL — Distributed Monitoring Platform

MonCTL is a distributed monitoring platform with a central management server and distributed collector nodes. Collectors pull job assignments from central, execute monitoring checks (ping, port, SNMP, custom apps), and forward results back for storage and alerting.

## Architecture

```
Browser --> HAProxy (VIP :443) --> central1-4 (:8444)
                                     |-- PostgreSQL (Patroni HA)
                                     |-- ClickHouse (replicated cluster)
                                     +-- Redis

Collectors (worker1-4) --> poll jobs from central --> execute checks --> forward results
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, SQLAlchemy async, Alembic |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4 |
| Time-series | ClickHouse (replicated, 3 nodes) |
| Relational DB | PostgreSQL 16 (Patroni HA, 2 nodes) |
| Cache | Redis |
| Proxy | HAProxy (TLS termination, round-robin) |
| Collector | Python 3.11, gRPC (peer communication), SQLite (local buffer) |
| TUI | Textual |

## Package Structure

```
packages/
  central/          Central management server (FastAPI + React SPA)
  collector/        Distributed collector node
  common/           Shared utilities
  sdk/              SDK package
docker/             Dockerfiles and deployment configs
```

## Central Server

The central server provides:

- **Device management** with CRUD, grouping, and templates
- **App framework** for monitoring checks (built-in + custom)
- **Collector management** with registration, approval, and group assignment
- **Credential vault** with AES-256-GCM encryption
- **Alerting engine** with configurable rules and thresholds
- **Multi-tenant support** with role-based access control
- **Time-series storage** in ClickHouse with configurable retention
- **REST API** with JWT cookie auth (web UI) and bearer token auth (collectors/management)

### API

- Web API: `/v1/` (devices, collectors, apps, credentials, alerts, etc.)
- Collector API: `/api/v1/` (job pull, result submission, heartbeat)

## Collector

Each collector node runs three services:

| Service | Purpose |
|---------|---------|
| `cache-node` | Cluster brain — gossip membership, distributed cache, gRPC peer communication |
| `poll-worker` | Pulls job assignments, executes checks, manages app virtualenvs |
| `forwarder` | Batches and ships results to central |

### Collector TUI Tools

- **`monctl-setup`** — Register collector with central, view connection status
- **`monctl-status`** — Monitor Docker containers, gossip membership, system resources

## Deployment

### Prerequisites

- Docker and Docker Compose on all nodes
- SSH access between build machine and servers

### Build & Deploy Collector

```bash
# Build
docker build --no-cache -t monctl-collector:latest \
  -f docker/Dockerfile.collector-v2 packages/collector/

# Distribute to workers
docker save monctl-collector:latest | ssh user@<worker-ip> 'docker load'

# Start/restart
ssh user@<worker-ip> 'cd /opt/monctl/collector && docker compose down && docker compose up -d'
```

### Build & Deploy Central

```bash
# Build (includes frontend)
docker build --platform linux/amd64 --no-cache -t monctl-central:latest \
  -f docker/Dockerfile.central .

# Distribute to central nodes
docker save monctl-central:latest | ssh user@<central-ip> 'docker load'

# Start/restart
ssh user@<central-ip> 'cd /opt/monctl/central && \
  docker compose -f docker-compose.central.yml down && \
  docker compose -f docker-compose.central.yml up -d'
```

### Configuration

Central is configured via environment variables with the `MONCTL_` prefix. Key settings:

| Variable | Description |
|----------|-------------|
| `MONCTL_DATABASE_URL` | PostgreSQL connection string |
| `MONCTL_CLICKHOUSE_HOST` | ClickHouse host |
| `MONCTL_REDIS_URL` | Redis connection string |
| `MONCTL_ADMIN_USERNAME` | Initial admin username (default: `admin`) |
| `MONCTL_ADMIN_PASSWORD` | Initial admin password (set on first boot) |
| `MONCTL_JWT_SECRET` | JWT signing secret |

Collectors are configured via `.env` at `/opt/monctl/collector/.env`:

| Variable | Description |
|----------|-------------|
| `NODE_ID` | Unique node identifier |
| `CENTRAL_URL` | Central server URL |
| `CENTRAL_API_KEY` | API key (set after registration) |
| `PEERS` | Comma-separated peer addresses for gossip |

## Development

```bash
# Install dev dependencies
cd packages/central && pip install -e ".[dev]"
cd packages/collector && pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check .
```

## License

Proprietary. All rights reserved.
