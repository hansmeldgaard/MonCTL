# Collector Deployment Guide

This guide covers deploying a MonCTL collector node from scratch — including host prerequisites, network requirements, and the deployment steps.

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
- In air-gapped environments, add central VIP to `/etc/hosts`:
  ```
  10.145.210.40  monctl-central
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

| Destination                 | Port | Protocol | Purpose                                |
| --------------------------- | ---- | -------- | -------------------------------------- |
| Central VIP (10.145.210.40) | 443  | HTTPS    | API (jobs, results, credentials, apps) |
| Central VIP (10.145.210.40) | 443  | WSS      | WebSocket command channel              |
| Monitored devices           | ICMP | —        | Ping checks                            |
| Monitored devices           | 161  | UDP      | SNMP polling                           |
| Monitored devices           | \*   | TCP      | Port checks, HTTP checks               |

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

The build server (or admin workstation) must be able to SSH as `monctl` to the collector node. Set up key-based auth:

```bash
# From the build server
ssh-copy-id monctl@<collector-ip>
```

---

## 4. Deployment

### 4.1 Environment File

Create `/opt/monctl/collector/.env` on the collector node:

```env
NODE_ID=worker1
CENTRAL_URL=https://10.145.210.40
CENTRAL_API_KEY=<collector-api-key-from-central>
VERIFY_SSL=false
MONCTL_COLLECTOR_ID=<uuid-from-central-after-approval>
```

- `NODE_ID` — unique per collector node (e.g., `worker1`, `worker2`)
- `CENTRAL_URL` — the central VIP (HAProxy)
- `CENTRAL_API_KEY` — shared collector API key (from central settings)
- `VERIFY_SSL` — set `false` for self-signed certificates
- `MONCTL_COLLECTOR_ID` — set after the collector is registered and approved in central

### 4.2 Build and Deploy

From the MonCTL repo on the build server:

```bash
./deploy.sh collector              # Build + deploy to all 4 workers
./deploy.sh collector 31 32        # Deploy to specific nodes (last IP octet)
./deploy.sh collector --no-build   # Skip build, reuse existing image
```

The deploy script:

1. Builds `monctl-collector:latest` from `Dockerfile.collector-v2`
2. Saves the image to a tar file
3. Transfers to all worker nodes in parallel via SCP
4. Loads the image and runs `docker compose up -d` on each node

### 4.3 Manual Deploy (single node)

If deploying to a new node not yet in `deploy.sh`:

```bash
# Copy compose file
scp docker/docker-compose.collector-prod.yml monctl@<ip>:/opt/monctl/collector/docker-compose.yml

# Copy image (if built locally)
docker save monctl-collector:latest | ssh monctl@<ip> 'docker load'

# Start
ssh monctl@<ip> 'cd /opt/monctl/collector && docker compose up -d'
```

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
- Verify `CENTRAL_URL` and `CENTRAL_API_KEY` in `.env`
- Ensure the collector can reach central: `curl -k https://10.145.210.40/v1/health`

### Jobs not being assigned

- Ensure the collector is **approved** (not just registered)
- Ensure `MONCTL_COLLECTOR_ID` is set in `.env` (without it, job filtering won't work)
- Check that the collector is assigned to a **Collector Group** with devices

### Time drift

- Large time drift causes ClickHouse insert issues (results appear at wrong timestamps)
- Fix: `sudo chronyc makestep` for immediate sync, then verify with `chronyc tracking`
