# Installing MonCTL

MonCTL is a distributed monitoring platform. This guide walks you from bare VMs to a live cluster in about 15 minutes.

## 1. Prerequisites

On every host that will run MonCTL:

| Requirement           | Minimum                                                 | Recommended                  |
| --------------------- | ------------------------------------------------------- | ---------------------------- |
| OS                    | Ubuntu 22.04 / 24.04, Debian 12, RHEL 9                 | Ubuntu 24.04                 |
| Docker Engine         | 24.x                                                    | 26.x                         |
| Docker Compose plugin | v2                                                      | v2.27+                       |
| RAM                   | 2 GB (co-located micro)                                 | 8 GB (per role)              |
| Disk                  | 20 GB (Postgres) / 100 GB (ClickHouse)                  | SSD                          |
| Time sync             | `systemd-timesyncd` or `chrony`                         | —                            |
| Network               | static IP, outbound 443, inbound 22 from installer host | —                            |
| SSH                   | key-based auth to a dedicated `monctl` user             | `NOPASSWD` sudo not required |

On the _operator laptop_ (not a target host):

- Python 3.11+ and `pipx`
- SSH key that the target hosts accept

## 2. Install the `monctl_ctl` CLI

```bash
pipx install monctl-installer
monctl_ctl --version
```

(Until the package is published to PyPI, install from the GitHub release wheel:
`pipx install https://github.com/hansmeldgaard/MonCTL/releases/download/v1.0.0/monctl_installer-1.0.0-py3-none-any.whl`.)

## 3. Describe your cluster

Run the interactive wizard:

```bash
monctl_ctl init
```

It asks for cluster name, hosts (name + IP + roles), and sizing. You can also start from one of the shipped examples:

```bash
# Fastest path — edit the example to your IPs, then point init at it:
cp inventory.example.small.yaml inventory.yaml
$EDITOR inventory.yaml
monctl_ctl init --from inventory.yaml --force
```

`init` writes two files:

- `inventory.yaml` — topology + sizing (safe to commit once IPs are stable)
- `secrets.env` — auto-generated passwords and keys (mode 0600, **never commit**)

### Pick a topology

**Micro (single host):** lab, demo, SMB pilot. See `inventory.example.micro.yaml`.

- 1 host running every role. No HA, no VIP. Works at 127.0.0.1.

**Small (3 hosts, PG HA + 1 CH + 1 central):** up to ~500 devices. See `inventory.example.small.yaml`.

- `mon1` is the busy box: Patroni primary + Redis + ClickHouse + central + a local collector.
- `mon2` is the Patroni replica + etcd voter.
- `mon3` is an etcd voter only (tiny VM fine).

**Large (15+ hosts, 4×2 CH, VIP+Sentinel):** 1000+ devices, high-retention metrics. See `inventory.example.large.yaml`.

- 3 central hosts with Patroni HA + HAProxy + keepalived.
- 8 ClickHouse nodes (4 shards × 2 replicas) with embedded Keeper on the first 3.
- N dedicated collector hosts.

**Optional: Superset BI** — add a host with `roles: [superset]` (small/large) or co-locate with `central` (micro). The installer brings up Superset behind HAProxy at `https://<vip>/bi/` with SSO against MonCTL. At most one host may carry `superset` (HA Superset is out of scope; see [`docs/superset.md`](docs/superset.md) for the access-tier and tenant-scope model).

## 4. Preflight

```bash
monctl_ctl validate
```

Parallel SSH checks on every host: Docker version, compose plugin, free RAM + disk, port availability per role, time sync. Warnings don't block deploy; **failures do**. Fix them and re-run.

## 5. Deploy

```bash
monctl_ctl deploy
```

Per host, `deploy`:

1. Renders a compose bundle for each role the host carries.
2. `scp`'s files into `/opt/monctl/<project>/` (mode 0600 for `.env`).
3. Runs `docker compose up -d --remove-orphans` in upstream-first order: postgres → etcd → redis → clickhouse → central → haproxy → collector.

Re-running `deploy` on an unchanged cluster is a no-op (state hash dedups). If you edit `inventory.yaml` and re-run, only the changed projects are touched.

## 6. Log in

At the end of `deploy`, the admin URL + password printed by `init` is still how you log in. Point a browser at:

- `https://<VIP>/` for the Large topology
- `https://<first-central-IP>:8443/` for Small / Micro

Username: `admin`. Password: the 20-char value from the red banner after `monctl_ctl init`.

## 7. Health check

```bash
monctl_ctl status
```

Per-host table with docker container count, central `/v1/health`, Patroni role + state, ClickHouse reachability, Redis replication role, Superset `/bi/health` (if the role is present). Exit 1 if any subsystem is down.

## 8. BI access (Superset)

If your inventory has a host with `roles: [superset]`, `monctl_ctl deploy` brings Superset up at `https://<vip>/bi/` (or `https://<central-IP>:8443/bi/` for non-VIP topologies). The first time, log in to MonCTL as admin → Settings → Users, set each user's **Superset access** tier (`viewer`/`analyst`/`admin`) and **Tenants** scope. Users at tier `none` cannot reach Superset. Tier and tenant changes take effect on the user's next OAuth login.

See [`docs/superset.md`](docs/superset.md) for the full access-tier model, tenant-scope row policies, and operator runbook (granting/revoking access, tier troubleshooting).

## 9. Day-two operations

- **Upgrade** to a new version: `monctl_ctl upgrade v1.1.0` (canary first, then rolling).
- **Logs**: `monctl_ctl logs <host> --project central --service central --tail 500 --follow`
- **SSH in**: `monctl_ctl ssh <host>` (passthrough to system `ssh`).
- **Add a collector host**: `monctl_ctl add-host col5 --address 10.0.0.35 --roles collector,docker_stats`. Appends to `inventory.yaml`, runs a targeted deploy on just the new host — existing hosts untouched (idempotent). Only leaf roles (`collector`, `docker_stats`) supported; adding postgres/etcd/CH nodes needs manual quorum-member registration first.
- **Remove a host**: `monctl_ctl remove-host col5`. Stops containers in reverse dependency order and strips from inventory. Use `--force` for hosts carrying non-leaf roles (after you've deregistered from Patroni/etcd/CH).

### Air-gapped installs

For customers who can't reach ghcr.io from their production network:

```bash
# On a jump host with internet access + Docker:
monctl_ctl bundle create --version v1.0.0 --out monctl-airgap-v1.0.0.tar.gz

# Transfer the tarball to the operator machine (scp / USB / approved channel).

# On the air-gapped operator machine, after pipx-installing monctl_ctl:
monctl_ctl bundle load monctl-airgap-v1.0.0.tar.gz
# → images are now in the local Docker daemon
monctl_ctl init       # as normal
monctl_ctl deploy     # as normal; will pull from GHCR unless you side-load per host
```

Pre-shipping images to every target host (so `monctl_ctl deploy` doesn't try to pull) currently requires manually scp-ing `images/*.tar` from the extracted bundle and running `docker load` on each host. A `deploy --image-source bundle` mode that automates this is planned.

## Firewall / ports

Open these inbound per role:

| Port       | Role                | Purpose                                                                 |
| ---------- | ------------------- | ----------------------------------------------------------------------- |
| 22         | all                 | SSH (installer only — lock down to operator IP)                         |
| 443        | haproxy             | UI + API (front door)                                                   |
| 8443       | central             | direct central API (behind HAProxy, but open inside the cluster subnet) |
| 5432       | postgres            | client connections (internal)                                           |
| 5433       | postgres (HA)       | Patroni internal                                                        |
| 8008       | postgres (HA)       | Patroni REST                                                            |
| 2379–2380  | etcd                | DCS quorum                                                              |
| 6379       | redis               | clients                                                                 |
| 26379      | redis (sentinel)    | quorum                                                                  |
| 8123, 9000 | clickhouse          | HTTP + native client                                                    |
| 9181, 9234 | clickhouse (keeper) | Keeper                                                                  |
| 8088       | superset            | Superset HTTP (behind HAProxy `/bi/*`)                                  |

Collectors only need outbound 443 to the central VIP/IP and whatever protocols their checks use (ICMP, SNMP 161/162, SSH 22, HTTPS 443, etc.).

## Troubleshooting

See [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

## Upgrades

See [`UPGRADE.md`](UPGRADE.md).
