# MonCTL

**A distributed monitoring platform — one idea, built end-to-end with [Claude Code](https://claude.com/claude-code).**

MonCTL watches your infrastructure: network devices, servers, containers, and anything else that speaks SNMP, SSH, ICMP, or HTTP. A central HA cluster owns configuration and storage; distributed collectors do the work and ship results back. You get a React UI, a REST API, alerting, events, dashboards, RBAC, multi-tenancy, and a pack system for sharing monitoring logic.

It is also an experiment in how far a single engineer can get with a clear product idea and an AI pair-programmer. Almost every line of code in this repository — backend, frontend, deployment tooling, docs — was written collaboratively with Claude Code. The commit history reads like a pairing session.

## Why this exists

Two goals, in order:

1. **Build a real monitoring platform** — not a demo. MonCTL runs in production on a 4-node central cluster (Patroni-backed Postgres, replicated ClickHouse, Redis sentinel, HAProxy + keepalived) with a fleet of collector nodes polling hundreds of devices on 30-second cycles.
2. **Push on the AI-assisted workflow** — keep the human in the loop for architecture, product taste, and deploy approval; delegate implementation, refactors, test-writing, and UI polish to the agent. See commits, PR descriptions, and the `docs/review/` folder for what that actually looks like at scale.

If you are curious how much of a real system one person plus Claude can ship in a few months, the answer is in `git log`.

## What's in the box

**Central server** — FastAPI + SQLAlchemy async, Alembic migrations, React 19 SPA.

- Device management, bulk import, device categories/types, labels, tenants
- Monitoring **apps** (ping, port, HTTP, SNMP, custom Python) with versioning and per-assignment overrides
- **Connector** system (SNMP, SSH) with credential resolution chain
- **Alerting engine** with a DSL (`rate(octets) * 8 / 1e6 > 500`), tiered severities, threshold hierarchy, and event policies
- **Monitoring packs** — ship and share bundles of apps, connectors, templates, and alerts
- Operational dashboards (aggregated health, performance top-N, config-change tracking)
- RBAC with custom roles, audit log, API keys, JWT cookie auth
- Centralized log collection and Docker-host monitoring

**Collector node** — three services:

| Service       | Purpose                                                                       |
| ------------- | ----------------------------------------------------------------------------- |
| `cache-node`  | Cluster brain — gossip membership, distributed cache, gRPC peer communication |
| `poll-worker` | Pulls job assignments, executes checks, manages app virtualenvs               |
| `forwarder`   | Batches and ships results to central                                          |

**Storage split** — PostgreSQL for relational state (devices, assignments, credentials), ClickHouse for time-series (ping latency, interface counters, alert history, config changes, events). Each time-series table has a `*_latest` materialized view for instant latest-per-entity queries.

## Architecture

```
         Browser
            │
            ▼
    HAProxy VIP (TLS)
            │
    ┌───────┴───────┐
    │               │
 central1      central2 ... (N nodes)
    │               │
    ├── Postgres (Patroni HA)
    ├── ClickHouse (replicated cluster)
    └── Redis (sentinel)

 Collectors (worker1..N)  ─── gossip ───  Collectors
    │                                       │
    └── poll jobs → execute → forward ──────┘
                         │
                         ▼
                      central
```

## Tech stack

| Layer       | Tech                                                            |
| ----------- | --------------------------------------------------------------- |
| Backend     | Python 3.11, FastAPI, SQLAlchemy 2 async, Alembic, Pydantic 2   |
| Frontend    | React 19, TypeScript 5.9, Vite 7, Tailwind v4, TanStack Query 5 |
| Time-series | ClickHouse (ReplicatedMergeTree)                                |
| Relational  | PostgreSQL 16 with Patroni HA                                   |
| Cache       | Redis with Sentinel                                             |
| Proxy       | HAProxy + Keepalived (VIP failover)                             |
| Collector   | Python 3.12, gRPC (peer comms), SQLite (local buffer)           |

## Installation

End-users install MonCTL with the `monctl_ctl` CLI, which renders per-host Docker Compose bundles from a declarative inventory file and handles SSH distribution, rolling upgrades, and air-gapped bundles.

→ **[INSTALL.md](INSTALL.md)** — from bare VMs to a live cluster in about 15 minutes.
→ **[UPGRADE.md](UPGRADE.md)** — rolling upgrade procedure.
→ **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** — common issues and recovery steps.

Example inventories at the repo root (`inventory.example.micro.yaml`, `inventory.example.small.yaml`, `inventory.example.large.yaml`) cover single-host to full-HA deployments.

## Repository layout

```
packages/
  central/          Central management server (FastAPI + React SPA)
  collector/        Distributed collector node
  common/           Shared utilities
  sdk/              SDK package (base classes, testing utilities)
  installer/        monctl_ctl CLI source
apps/               Reference source for built-in monitoring apps
packs/              Built-in monitoring packs (auto-imported on first boot)
docker/             Dockerfiles and deployment templates
docs/               Guides, deployment notes, code-review reports
scripts/            Dev utilities (e2e smoke, seed data, deck generator)
```

## Development

```bash
# Clone
git clone https://github.com/hansmeldgaard/MonCTL.git
cd MonCTL

# Install dev dependencies
cd packages/central   && pip install -e ".[dev]" && cd -
cd packages/collector && pip install -e ".[dev]" && cd -

# Lint + type-check
ruff check .
cd packages/central/frontend && npm install && npx tsc --noEmit
```

For contributing guidelines, local dev tips, and the "gotchas" list accumulated while building MonCTL, see [`CLAUDE.md`](CLAUDE.md) — it is the onboarding doc that the AI agent reads, and it happens to also be the best onboarding doc for humans.

## Built with Claude Code

This project is an honest answer to the question _"how much of a real distributed system can one engineer ship with an AI pair-programmer?"_

- **Pairing, not autopilot.** Architecture decisions, product scope, schema design, deploy approval — human. Implementation, refactors, test suites, UI polish, docs — agent, reviewed by human.
- **Verified, not vibed.** Every feature is tested in the real UI via the Playwright MCP before it's declared done. CI, alembic migrations, and rolling deploys guard the production cluster.
- **Memory and gotchas are first-class.** The `CLAUDE.md` file and the agent's persistent memory record hard-won lessons ("ClickHouse MVs freeze their column list at CREATE time", "collector delta-sync keys on `updated_at`, raw SQL must bump it manually") so the same bug doesn't get rediscovered twice.
- **Full traceability.** Read the commit history, the PR descriptions, and the `docs/review/` reports. Every major subsystem has a paper trail.

If you're evaluating AI-assisted engineering for real projects, MonCTL is a case study you can actually run.

## Status

Production in use. APIs and schemas are stabilising but not yet versioned for external contracts — pin to a commit if you depend on them.

## License

[MIT](LICENSE) — use it, fork it, ship it. **No warranty, no liability, use at your own risk.** If something breaks your monitoring stack at 3 a.m., that's on you. Pull requests welcome.
