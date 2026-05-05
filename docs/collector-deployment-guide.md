# Collector Node Reference

This is a per-host reference for collector nodes — what the host needs,
how to register it with central, what containers run on it, and how to
debug it. **It is not a deployment runbook**: the actual install/upgrade
flow runs from your operator laptop via `monctl_ctl deploy`. See
[`INSTALL.md`](../INSTALL.md) for the platform-wide setup, including
the `collector` role inventory entries and the per-host key flow.

The sections below assume:

- you've already added the host to your inventory (`monctl_ctl inventory edit`)
- you've run `monctl_ctl deploy` at least once for this cluster

If either is false, start at `INSTALL.md` and come back here when you
need to add another collector or troubleshoot one.

---

## 1. Host Prerequisites

### Operating System

- **Ubuntu 22.04 LTS** (or later) — 64-bit (amd64)
- Minimal server install (no GUI required)

### Hardware (minimum per collector node)

| Resource | Minimum | Recommended |
| -------- | ------- | ----------- |
| CPU      | 2 vCPU  | 4 vCPU      |
| RAM      | 2 GB    | 4 GB        |
| Disk     | 20 GB   | 40 GB       |

> Disk usage is primarily Docker images (~500 MB) and app venvs. Monitor `/var/lib/docker` usage.

### Docker

Docker Engine must be installed and running. The `monctl` user must be in the `docker` group.

```bash
# Install Docker (official method)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker monctl
```

Verify:

```bash
docker info
docker compose version   # must be v2+
```

---

## 2. Network Requirements

### IP Configuration

- Static IP address (or DHCP reservation)
- The collector must be able to reach central on HTTPS (port 443)

### DNS

- The host must be able to resolve DNS names (configure `/etc/resolv.conf` or systemd-resolved)
- If using internal DNS, ensure the central VIP hostname (if any) resolves correctly
- In air-gapped environments, add the central VIP to `/etc/hosts` so
  the collector can resolve it without external DNS:
  ```
  <central-vip-ip>  <central-hostname>
  ```

### NTP / Time Synchronization

Accurate time is critical — monitoring timestamps, certificate validation, and job scheduling all depend on it.

```bash
# Verify NTP is active
timedatectl status
# Should show: NTP service: active, System clock synchronized: yes

# If not configured:
sudo apt install -y chrony
sudo systemctl enable --now chrony
chronyc tracking
```

> Ensure time drift stays below 1 second. Large drift causes result timestamp mismatches in ClickHouse.

### Routing

The collector needs outbound access to:

| Destination       | Port | Protocol | Purpose                                |
| ----------------- | ---- | -------- | -------------------------------------- |
| Central VIP       | 443  | HTTPS    | API (jobs, results, credentials, apps) |
| Central VIP       | 443  | WSS      | WebSocket command channel              |
| Monitored devices | ICMP | —        | Ping checks                            |
| Monitored devices | 161  | UDP      | SNMP polling                           |
| Monitored devices | 22   | TCP      | SSH-based apps (where applicable)      |
| Monitored devices | \*   | TCP      | Port checks, HTTP checks               |

No inbound ports need to be open from the internet. Port 50051 (gRPC) is only used internally within each collector's Docker network.

### Firewall

If `ufw` or `iptables` is active, ensure the above outbound traffic is allowed. For ICMP (ping checks):

```bash
# Verify ICMP is not blocked
ping -c 1 <monitored-device-ip>
```

---

## 3. System User

All collector nodes use the `monctl` user:

```bash
sudo adduser --system --group --home /home/monctl --shell /bin/bash monctl
sudo usermod -aG docker monctl
```

Create the deployment directory:

```bash
sudo mkdir -p /opt/monctl/collector
sudo chown monctl:monctl /opt/monctl/collector
sudo mkdir -p /etc/monctl
sudo chown monctl:monctl /etc/monctl
```

### SSH Access

The operator laptop running `monctl_ctl` must be able to SSH as `monctl` to the collector node with key-based auth. The installer doesn't deploy keys for you — set this up before `monctl_ctl preflight`:

```bash
# From the operator laptop
ssh-copy-id monctl@<collector-ip>
ssh monctl@<collector-ip> 'docker info'   # smoke-test
```

---

## 4. Deployment

The actual deploy is a single command from the operator laptop —
**not** something you run on the collector itself:

```bash
monctl_ctl deploy --role collector --host <hostname>
```

`monctl_ctl deploy` renders `/opt/monctl/collector/docker-compose.yml`
plus `.env` from your inventory, transfers the image (or pulls it from
the configured registry), runs `docker compose up -d`, and registers
the host with central via `register-collectors` post-step (Wave 2C —
mints a per-host API key and writes it back into `.env`). The full
end-to-end flow is documented in [`INSTALL.md`](../INSTALL.md) §5;
don't reproduce it here, the canonical version moves with the CLI.

### What ends up in `.env`

After `monctl_ctl deploy` finishes, `/opt/monctl/collector/.env` looks
roughly like:

```env
NODE_ID=<host_name from inventory>
CENTRAL_URL=https://<cluster.cluster_vip from inventory>
CENTRAL_API_KEY=<per-host key minted by register-collectors>
VERIFY_SSL=true
MONCTL_COLLECTOR_ID=<assigned by central on first registration>
PEER_TOKEN=<derived per-host from cluster.peer_token_seed>
```

A few things to know before editing this file by hand:

- `CENTRAL_API_KEY` is **per-host** as of Wave 2 (PR #186/#187/#188). If
  you regenerate it without going through `monctl_ctl register-collectors`
  the collector will be unauthenticated until you re-run that command —
  preserve it across redeploys.
- `VERIFY_SSL` defaults to `true`. Only set it to `false` for development
  clusters with self-signed certs that aren't pinned in
  `MONCTL_COLLECTOR_CA_BUNDLE`. Production should ship a real CA bundle
  and leave verify on.
- `MONCTL_COLLECTOR_ID` is empty on the very first start; central
  populates it on the first heartbeat and the entrypoint persists it
  back into `.env`. Don't pre-fill it — let central own that value.
- `PEER_TOKEN` is derived from `cluster.peer_token_seed` via HMAC-SHA256
  (M-INST-012). Don't reset it unless you're rotating the cluster seed
  for every host at once; otherwise cache-node ↔ poll-worker gRPC stops
  authenticating.

### Adding a new collector host

```bash
monctl_ctl inventory edit       # add the host under cluster.collectors
monctl_ctl preflight             # confirms SSH, Docker, ports, time-sync
monctl_ctl deploy --role collector --host <new-hostname>
```

Then approve and group-assign from the UI (§5 below). No need to redeploy
existing hosts.

---

## 5. Registration and Approval

On first start, the collector registers with central automatically (via `collector-entrypoint.sh`). After registration:

1. Log into the MonCTL web UI
2. Go to **Collectors** page
3. The new collector appears with status **Pending**
4. Click **Approve** to activate it
5. Assign it to a **Collector Group** (determines which devices it polls)

Once approved, the collector starts pulling jobs and executing monitoring checks.

---

## 6. Verification Checklist

After deployment, verify:

- [ ] `docker ps` shows all containers running: `cache-node`, `poll-worker-1`, `forwarder`, `monctl-docker-stats`
- [ ] `docker logs cache-node` shows "Central server is ready" and successful job sync
- [ ] Collector appears in the web UI under Collectors
- [ ] Time is synchronized: `timedatectl status` shows NTP active
- [ ] Ping works from the collector to monitored devices
- [ ] SNMP works: `docker exec poll-worker-1 python -c "import pysnmp; print('ok')"`
- [ ] No DNS resolution errors in `docker logs forwarder`

---

## 7. Compose Services

Each collector node runs 4 containers:

| Container             | Role                                             | Resource Limit |
| --------------------- | ------------------------------------------------ | -------------- |
| `cache-node`          | Cluster brain — job scheduling, credential cache | —              |
| `poll-worker-1`       | Executes monitoring checks (ping, SNMP, HTTP)    | 1 GB RAM       |
| `forwarder`           | Batches and ships results to central             | —              |
| `monctl-docker-stats` | Reports Docker host stats to central             | —              |

### Memory Management

Poll workers have a known memory growth pattern. The `mem_limit: 1g` in compose ensures automatic restart if a worker exceeds 1 GB. The worker also runs `gc.collect()` + `malloc_trim(0)` after each job, and uses `MALLOC_ARENA_MAX=2` to limit glibc arena fragmentation.

---

## 8. Troubleshooting

### Collector not appearing in UI

- Check `docker logs cache-node` for registration errors
- Verify `CENTRAL_URL` and `CENTRAL_API_KEY` in `/opt/monctl/collector/.env`
- Ensure the collector can reach central: `curl -k "${CENTRAL_URL}/v1/health"` (substituting the value from `.env`; expect a 200 with `{"status":"ok"}`)

### Jobs not being assigned

- Ensure the collector is **approved** (not just registered)
- Ensure `MONCTL_COLLECTOR_ID` is set in `.env` (without it, job filtering won't work)
- Check that the collector is assigned to a **Collector Group** with devices

### Time drift

- Large time drift causes ClickHouse insert issues (results appear at wrong timestamps)
- Fix: `sudo chronyc makestep` for immediate sync, then verify with `chronyc tracking`
