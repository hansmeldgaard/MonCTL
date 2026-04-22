"""Lightweight Docker stats sidecar for MonCTL.

Collects container stats in a background thread every 15 seconds.
Serves cached results instantly on GET /stats.
Also provides /logs, /events, /images, /system endpoints.
"""

import json
import os
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

import ssl
from urllib.request import Request, urlopen
from urllib.error import URLError

import docker

client = docker.from_env()
HOSTNAME = os.environ.get("MONCTL_HOST_LABEL", socket.gethostname())
COLLECT_INTERVAL = int(os.environ.get("COLLECT_INTERVAL", "15"))

# ── Push mode (worker → central) ────────────────────────────────────────────
PUSH_URL = os.environ.get("MONCTL_PUSH_URL", "")
PUSH_API_KEY = os.environ.get("MONCTL_PUSH_API_KEY", "")
PUSH_INTERVAL = int(os.environ.get("MONCTL_PUSH_INTERVAL", "15"))
# Default to verified TLS; compose files explicitly set "false" on deployments
# that push to the self-signed HAProxy VIP (F-X-010 — no silent TLS disabling).
PUSH_VERIFY_SSL = os.environ.get("MONCTL_PUSH_VERIFY_SSL", "true").lower() in ("true", "1", "yes")

_cached_stats: dict = {}
_cached_stats_lock = threading.Lock()

# ── Ring buffers ──────────────────────────────────────────────────────────────

# Container logs: {container_name: deque(maxlen=500)}
_log_buffers: dict[str, deque] = {}
_LOG_LINES_PER_CONTAINER = 500
_MAX_TRACKED_CONTAINERS = 20
_log_lock = threading.Lock()

# Docker events: deque of event dicts, newest last
_event_buffer: deque = deque(maxlen=500)
_event_lock = threading.Lock()


def _parse_qs_single(path: str) -> dict[str, str]:
    """Parse query string, return single-value dict."""
    qs = parse_qs(urlparse(path).query)
    return {k: v[0] for k, v in qs.items()}


# ── Background threads ───────────────────────────────────────────────────────

def _log_collector():
    """Background thread: tail logs from all running containers into ring buffers."""
    threads: dict[str, threading.Thread] = {}

    def _tail_container(container):
        name = container.name
        buf = deque(maxlen=_LOG_LINES_PER_CONTAINER)
        with _log_lock:
            _log_buffers[name] = buf
        try:
            for line in container.logs(stream=True, follow=True, tail=50, timestamps=True):
                decoded = line.decode("utf-8", errors="replace").rstrip("\n")
                # Docker timestamps=True format: "2026-04-04T17:11:55.242448430Z message"
                # Split into structured {timestamp, message} for the log shipper
                z_pos = decoded.find('Z ', 19, 40)
                if z_pos > 0 and decoded[4] == '-' and decoded[10] == 'T':
                    ts = decoded[:z_pos + 1]
                    msg = decoded[z_pos + 2:]
                    buf.append({"timestamp": ts, "message": msg})
                else:
                    buf.append(decoded)
        except Exception:
            pass  # container stopped or removed

    while True:
        try:
            running = {c.name: c for c in client.containers.list() if c.status == "running"}
            # Start tailing new containers (respect max)
            for name, c in running.items():
                if name not in threads and len(threads) < _MAX_TRACKED_CONTAINERS:
                    t = threading.Thread(target=_tail_container, args=(c,), daemon=True)
                    t.start()
                    threads[name] = t
            # Clean up dead threads
            for name in list(threads):
                if not threads[name].is_alive():
                    del threads[name]
                    with _log_lock:
                        _log_buffers.pop(name, None)
        except Exception:
            pass
        time.sleep(10)


def _event_listener():
    """Background thread: listen to Docker events and buffer them."""
    while True:
        try:
            for event in client.events(decode=True):
                entry = {
                    "time": event.get("time", 0),
                    "time_iso": datetime.fromtimestamp(
                        event.get("time", 0), tz=timezone.utc
                    ).isoformat(),
                    "type": event.get("Type", ""),
                    "action": event.get("Action", ""),
                    "actor_id": event.get("Actor", {}).get("ID", "")[:12],
                    "actor_name": event.get("Actor", {}).get("Attributes", {}).get("name", ""),
                    "actor_image": event.get("Actor", {}).get("Attributes", {}).get("image", ""),
                    "exit_code": event.get("Actor", {}).get("Attributes", {}).get("exitCode"),
                }
                with _event_lock:
                    _event_buffer.append(entry)
        except Exception:
            time.sleep(5)


# ── NTP status ───────────────────────────────────────────────────────────────

def _collect_ntp_status() -> dict:
    """Check NTP synchronization status from the host filesystem.

    Uses /run/systemd/timesync/synchronized (exists only when synced)
    and /etc/systemd/timesyncd.conf for the configured server.
    """
    result: dict = {"synchronized": False, "server": None, "offset_ms": None}

    # Check sync status — file exists only when timesyncd has synced
    result["synchronized"] = os.path.isfile("/host_root/run/systemd/timesync/synchronized")

    # Read configured NTP server from timesyncd.conf
    try:
        with open("/host_root/etc/systemd/timesyncd.conf") as f:
            for line in f:
                line = line.strip()
                if line.startswith("NTP="):
                    result["server"] = line.split("=", 1)[1].strip()
                    break
                elif line.startswith("FallbackNTP=") and not result["server"]:
                    result["server"] = line.split("=", 1)[1].strip().split()[0]
    except Exception:
        pass

    # Also check chrony if installed (some hosts may use chrony instead)
    if not result["server"]:
        try:
            with open("/host_root/etc/chrony/chrony.conf") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("server ") or line.startswith("pool "):
                        result["server"] = line.split()[1]
                        break
        except Exception:
            pass

    return result


# ── Stats collection ─────────────────────────────────────────────────────────

def _collect_stats() -> dict:
    containers = []

    for c in client.containers.list(all=True):
        info = {
            "name": c.name,
            "image": c.image.tags[0] if c.image.tags else c.image.short_id,
            "status": c.status,
            "health": None,
            "started_at": c.attrs.get("State", {}).get("StartedAt"),
            "restart_count": c.attrs.get("RestartCount", 0),
        }

        health = c.attrs.get("State", {}).get("Health", {})
        if health:
            info["health"] = health.get("Status")

        if c.status == "running":
            try:
                stats = c.stats(stream=False)
                cpu_delta = (
                    stats["cpu_stats"]["cpu_usage"]["total_usage"]
                    - stats["precpu_stats"]["cpu_usage"]["total_usage"]
                )
                system_delta = (
                    stats["cpu_stats"]["system_cpu_usage"]
                    - stats["precpu_stats"]["system_cpu_usage"]
                )
                cpu_count = stats["cpu_stats"].get("online_cpus", 1)
                cpu_pct = round(
                    (cpu_delta / system_delta) * cpu_count * 100, 2
                ) if system_delta > 0 else 0.0

                mem = stats.get("memory_stats", {})
                mem_usage = mem.get("usage", 0)
                mem_limit = mem.get("limit", 0)
                mem_cache = mem.get("stats", {}).get("cache", 0)
                mem_working = mem_usage - mem_cache

                networks = stats.get("networks", {})
                net_rx = sum(n.get("rx_bytes", 0) for n in networks.values())
                net_tx = sum(n.get("tx_bytes", 0) for n in networks.values())

                blkio = stats.get("blkio_stats", {}).get(
                    "io_service_bytes_recursive", []
                ) or []
                blk_read = sum(
                    e.get("value", 0) for e in blkio if e.get("op") == "read"
                )
                blk_write = sum(
                    e.get("value", 0) for e in blkio if e.get("op") == "write"
                )

                pids = stats.get("pids_stats", {}).get("current", 0)

                info.update({
                    "cpu_pct": cpu_pct,
                    "mem_usage_bytes": mem_working,
                    "mem_limit_bytes": mem_limit,
                    "mem_pct": round(
                        (mem_working / mem_limit) * 100, 1
                    ) if mem_limit > 0 else 0,
                    "net_rx_bytes": net_rx,
                    "net_tx_bytes": net_tx,
                    "block_read_bytes": blk_read,
                    "block_write_bytes": blk_write,
                    "pids": pids,
                })
            except Exception:
                info.update({
                    "cpu_pct": None, "mem_usage_bytes": None,
                    "mem_limit_bytes": None, "mem_pct": None,
                })

        containers.append(info)

    disk = shutil.disk_usage("/host_root") if os.path.exists("/host_root") else None

    return {
        "hostname": HOSTNAME,
        "collected_at": time.time(),
        "container_count": len([c for c in containers if c["status"] == "running"]),
        "total_containers": len(containers),
        "host": {
            "disk_total_bytes": disk.total if disk else None,
            "disk_used_bytes": disk.used if disk else None,
            "disk_free_bytes": disk.free if disk else None,
        },
        "containers": sorted(containers, key=lambda c: c["name"]),
    }


def _background_collector():
    global _cached_stats
    while True:
        try:
            stats = _collect_stats()
            with _cached_stats_lock:
                _cached_stats = stats
        except Exception as e:
            print(f"Collection error: {e}")
        time.sleep(COLLECT_INTERVAL)


# ── Host namespace execution ────────────────────────────────────────────────
#
# Running apt/dpkg via `chroot /host_root` only changes the filesystem view —
# the process still runs in the container's namespaces and with the container's
# capabilities, so /dev, /proc, /sys, /run, /var/run (tmpfs), DBus and the
# kernel AppArmor/device-mapper interfaces are all either absent or forbidden.
# That breaks AppArmor profile reloads, initramfs regeneration, and DBus-based
# postinst scripts.
#
# `nsenter -t 1 -a` enters the host init's namespaces so commands behave as if
# executed directly on the host. Requires the container to run with
# `pid: host` + `privileged: true` (see docker-compose.docker-stats.yml and
# docker-compose.collector-prod.yml).

def _host_exec(
    script: str,
    timeout: int = 120,
    check: bool = False,
) -> subprocess.CompletedProcess:
    """Run a shell script in the host's root namespace via nsenter.

    Prefer this over `chroot /host_root` for any operation that touches:
    runtime state (/run, /var/run), the kernel (AppArmor, device-mapper),
    DBus, systemd, or triggers initramfs/apparmor reloads.
    """
    return subprocess.run(
        [
            "nsenter",
            "--target", "1",
            "--mount", "--uts", "--ipc", "--net", "--pid",
            "--",
            "bash", "-c", script,
        ],
        capture_output=True, text=True, timeout=timeout, check=check,
    )


# ── Post-install output scanner ────────────────────────────────────────────
#
# apt/dpkg may exit 0 even when postinst scripts or triggers fail (e.g.
# apparmor_parser errors are logged but don't propagate, initramfs-tools
# triggers print "Command failed." but still return success at the top level).
# Scan the output for known failure markers so the upgrade job can surface
# them to the operator instead of silently reporting success.

POSTINST_FAILURE_MARKERS = (
    "apparmor_parser: ",  # "Access denied", "Unable to replace", etc.
    "Error: At least one profile failed to load",
    "Failed to connect to bus",
    "/dev/mapper/control: open failed",
    "Failure to communicate with kernel device-mapper driver",
    "dpkg: error processing",
    "Command failed.",
    "update-initramfs: failed",
    "GDBus.Error:",
)


def _gc_apt_job_files(max_age_seconds: int = 3600) -> int:
    """Delete stale /var/run/monctl-apt-*.{log,rc} files older than max_age.

    Status reads are idempotent — files live on so that callers can re-poll
    after a crash without losing the result. A lightweight sweep keeps
    /var/run from growing without bound. Reset-failed cleans the transient
    systemd unit record (no-op on active or already-cleaned).
    """
    script = (
        "for f in /var/run/monctl-apt-*.log /var/run/monctl-apt-*.rc; do "
        "  [ -e \"$f\" ] || continue; "
        f"  if [ $(($(date +%s) - $(stat -c %Y \"$f\"))) -gt {max_age_seconds} ]; then "
        "    rm -f \"$f\"; "
        "  fi; "
        "done; "
        "for u in $(systemctl list-units 'monctl-apt-*' --state=inactive,failed --no-legend -o cat 2>/dev/null | awk '{print $1}'); do "
        "  systemctl reset-failed \"$u\" 2>/dev/null; "
        "done; true"
    )
    try:
        _host_exec(script, timeout=30)
        return 0
    except Exception:
        return -1


def _scan_postinst_failures(output: str) -> list[str]:
    """Return a deduplicated list of warning lines from an apt/dpkg output."""
    seen: set[str] = set()
    warnings: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped in seen:
            continue
        for marker in POSTINST_FAILURE_MARKERS:
            if marker in stripped:
                seen.add(stripped)
                warnings.append(stripped)
                break
    return warnings


class StatsHandler(BaseHTTPRequestHandler):
    def _json_response(self, code: int, data):
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        except BrokenPipeError:
            pass

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/stats":
            with _cached_stats_lock:
                data = _cached_stats
            self._json_response(200, data)

        elif path == "/health":
            self._json_response(200, {"status": "ok"})

        elif path == "/logs":
            params = _parse_qs_single(self.path)
            container = params.get("container", "")
            tail = min(int(params.get("tail", "100")), _LOG_LINES_PER_CONTAINER)

            if not container:
                self._json_response(400, {"error": "container parameter required"})
                return

            with _log_lock:
                buf = _log_buffers.get(container)
                lines = list(buf)[-tail:] if buf else []

            self._json_response(200, {
                "container": container,
                "lines": lines,
                "count": len(lines),
                "buffer_size": _LOG_LINES_PER_CONTAINER,
            })

        elif path == "/events":
            params = _parse_qs_single(self.path)
            since = float(params.get("since", "0"))
            limit = min(int(params.get("limit", "100")), 500)

            with _event_lock:
                events = [e for e in _event_buffer if e["time"] >= since]
            events = events[-limit:]

            self._json_response(200, {
                "events": events,
                "count": len(events),
                "buffer_size": _event_buffer.maxlen,
                "oldest_ts": _event_buffer[0]["time"] if _event_buffer else None,
            })

        elif path == "/images":
            images = []
            for img in client.images.list(all=True):
                tags = img.tags or []
                images.append({
                    "id": img.short_id,
                    "tags": tags,
                    "size_bytes": img.attrs.get("Size", 0),
                    "created": img.attrs.get("Created", ""),
                    "dangling": len(tags) == 0,
                })

            volumes = []
            for vol in client.volumes.list():
                volumes.append({
                    "name": vol.name,
                    "driver": vol.attrs.get("Driver", ""),
                    "mountpoint": vol.attrs.get("Mountpoint", ""),
                    "created": vol.attrs.get("CreatedAt", ""),
                })

            try:
                df = client.df()
                space_summary = {
                    "images_total_bytes": sum(i.get("Size", 0) for i in df.get("Images", [])),
                    "images_reclaimable_bytes": sum(
                        i.get("Size", 0) for i in df.get("Images", [])
                        if i.get("Containers", 0) == 0
                    ),
                    "volumes_total_bytes": sum(
                        v.get("UsageData", {}).get("Size", 0)
                        for v in df.get("Volumes", [])
                    ),
                    "build_cache_bytes": sum(
                        b.get("Size", 0) for b in df.get("BuildCache", [])
                    ),
                }
            except Exception:
                space_summary = None

            self._json_response(200, {
                "images": sorted(images, key=lambda i: i["size_bytes"], reverse=True),
                "volumes": sorted(volumes, key=lambda v: v["name"]),
                "space_summary": space_summary,
                "image_count": len(images),
                "dangling_count": sum(1 for i in images if i["dangling"]),
                "volume_count": len(volumes),
            })

        elif path == "/system":
            info = client.info()

            load_avg = None
            cpu_count = info.get("NCPU", 1)
            try:
                with open("/host_root/proc/loadavg") as f:
                    parts = f.read().split()
                    load_avg = {
                        "1m": float(parts[0]),
                        "5m": float(parts[1]),
                        "15m": float(parts[2]),
                    }
            except Exception:
                pass

            mem = {}
            try:
                with open("/host_root/proc/meminfo") as f:
                    for line in f:
                        parts = line.split()
                        key = parts[0].rstrip(":")
                        if key in ("MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached", "SwapTotal", "SwapFree"):
                            mem[key] = int(parts[1]) * 1024
            except Exception:
                pass

            uptime_seconds = None
            try:
                with open("/host_root/proc/uptime") as f:
                    uptime_seconds = float(f.read().split()[0])
            except Exception:
                pass

            disk = shutil.disk_usage("/host_root") if os.path.exists("/host_root") else None

            ntp = _collect_ntp_status()

            self._json_response(200, {
                "hostname": HOSTNAME,
                "docker": {
                    "version": info.get("ServerVersion", ""),
                    "api_version": info.get("ApiVersion", ""),
                    "storage_driver": info.get("Driver", ""),
                    "os": info.get("OperatingSystem", ""),
                    "kernel": info.get("KernelVersion", ""),
                    "architecture": info.get("Architecture", ""),
                    "cpus": cpu_count,
                    "memory_bytes": info.get("MemTotal", 0),
                },
                "host": {
                    "load_avg": load_avg,
                    "cpu_count": cpu_count,
                    "mem_total_bytes": mem.get("MemTotal"),
                    "mem_available_bytes": mem.get("MemAvailable"),
                    "mem_free_bytes": mem.get("MemFree"),
                    "mem_buffers_bytes": mem.get("Buffers"),
                    "mem_cached_bytes": mem.get("Cached"),
                    "swap_total_bytes": mem.get("SwapTotal"),
                    "swap_free_bytes": mem.get("SwapFree"),
                    "uptime_seconds": uptime_seconds,
                    "ntp": ntp,
                    "disk_total_bytes": disk.total if disk else None,
                    "disk_used_bytes": disk.used if disk else None,
                    "disk_free_bytes": disk.free if disk else None,
                },
                "containers": {
                    "running": info.get("ContainersRunning", 0),
                    "paused": info.get("ContainersPaused", 0),
                    "stopped": info.get("ContainersStopped", 0),
                    "total": info.get("Containers", 0),
                },
            })

        elif path == "/os/check":
            try:
                params = _parse_qs_single(self.path)
                proxy_url = params.get("proxy_url", "")
                proxy_env = f"http_proxy={proxy_url} https_proxy={proxy_url} " if proxy_url else ""
                result = _host_exec(
                    f"{proxy_env}apt-get update -qq 2>/dev/null && apt list --upgradable 2>/dev/null",
                    timeout=120,
                )
                updates = []
                for line in result.stdout.strip().splitlines():
                    if "[upgradable from:" not in line:
                        continue
                    try:
                        # Format: package/suite version arch [upgradable from: old_version]
                        pkg_part, rest = line.split("/", 1)
                        parts = rest.split()
                        new_ver = parts[1] if len(parts) > 1 else ""
                        old_ver = ""
                        if "from:" in line:
                            old_ver = line.split("from:")[-1].strip().rstrip("]")
                        severity = "security" if "-security" in line else "normal"
                        updates.append({
                            "package": pkg_part.strip(),
                            "current": old_ver,
                            "new": new_ver,
                            "severity": severity,
                        })
                    except Exception:
                        continue
                self._json_response(200, {"updates": updates, "error": None})
            except subprocess.TimeoutExpired:
                self._json_response(500, {"updates": [], "error": "apt-get update timed out"})
            except Exception as e:
                self._json_response(500, {"updates": [], "error": str(e)})

        elif path == "/os/apt-source-status":
            # Check if /etc/apt/sources.list.d/monctl.list is configured
            try:
                check = subprocess.run(
                    ["chroot", "/host_root", "test", "-f",
                     "/etc/apt/sources.list.d/monctl.list"],
                    capture_output=True, timeout=5,
                )
                configured = check.returncode == 0
            except Exception:
                configured = False
            self._json_response(200, {"configured": configured})

        elif path == "/os/reboot-required":
            # /run (and its /var/run symlink) is a tmpfs — NOT visible in the
            # /host_root bind mount, so chroot /host_root always reports
            # "not found". Enter the host's mount namespace via nsenter
            # instead, where /run is the real runtime tmpfs.
            required = False
            packages: list[str] = []
            try:
                result = _host_exec(
                    "if [ -f /run/reboot-required ]; then "
                    "echo REQUIRED; "
                    "cat /run/reboot-required.pkgs 2>/dev/null || true; "
                    "fi",
                    timeout=5,
                )
                lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
                if lines and lines[0] == "REQUIRED":
                    required = True
                    packages = lines[1:]
            except Exception:
                pass
            self._json_response(200, {
                "reboot_required": required,
                "packages": packages,
            })

        elif path == "/os/installed":
            try:
                result = _host_exec(
                    "dpkg-query -W -f '${Package}\t${Version}\t${Architecture}\t${Status}\n'",
                    timeout=30,
                )
                packages = []
                for line in result.stdout.strip().splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 4 and "installed" in parts[3]:
                        packages.append({
                            "package": parts[0],
                            "version": parts[1],
                            "architecture": parts[2] if len(parts) > 2 else "amd64",
                        })
                self._json_response(200, {"packages": packages})
            except subprocess.TimeoutExpired:
                self._json_response(500, {"packages": [], "error": "dpkg-query timed out"})
            except Exception as e:
                self._json_response(500, {"packages": [], "error": str(e)})

        elif path == "/os/install/status":
            # Polled by central to get status of a /os/install job launched
            # earlier. Caller retries across sidecar restarts — this endpoint
            # is idempotent. Cleans up state files once the job reaches a
            # terminal state and the caller has seen it.
            params = _parse_qs_single(self.path)
            job_id = params.get("job_id", "")
            if not re.match(r"^[a-f0-9]{12}$", job_id):
                self._json_response(400, {"error": "invalid job_id"})
                return
            log_path = f"/var/run/monctl-apt-{job_id}.log"
            rc_path = f"/var/run/monctl-apt-{job_id}.rc"
            unit = f"monctl-apt-{job_id}"
            # Read log (may be partial while running).
            log_res = _host_exec(
                f"cat {shlex.quote(log_path)} 2>/dev/null; true",
                timeout=15,
            )
            rc_res = _host_exec(
                f"cat {shlex.quote(rc_path)} 2>/dev/null; true",
                timeout=10,
            )
            output = log_res.stdout
            rc_raw = rc_res.stdout.strip()
            if rc_raw.isdigit():
                rc = int(rc_raw)
                state = "completed" if rc == 0 else "failed"
                warnings = _scan_postinst_failures(output)
                # Idempotent: files are NOT deleted here so callers can safely
                # re-poll after a crash/restart without losing the result.
                # Stale files are GC'd by _gc_apt_job_files (1h TTL).
                self._json_response(200, {
                    "state": state,
                    "returncode": rc,
                    "success": rc == 0,
                    "output": output,
                    "warnings": warnings,
                })
                return
            # No rc file yet — job still running OR died without writing rc.
            active = _host_exec(
                f"systemctl is-active {shlex.quote(unit)} 2>&1; true",
                timeout=10,
            )
            state_word = active.stdout.strip().splitlines()[-1] if active.stdout else ""
            if state_word == "active" or state_word == "activating":
                self._json_response(200, {
                    "state": "running",
                    "output": output,
                })
            else:
                # Unit is inactive/failed/unknown and no rc was ever written.
                # Either the unit was cleaned up cleanly (edge case) or
                # systemd killed it. Report failed so caller can move on.
                self._json_response(200, {
                    "state": "failed",
                    "returncode": -1,
                    "success": False,
                    "output": output
                        + f"\n[status] systemd unit '{unit}' ended without writing rc"
                          f" (state={state_word or 'unknown'})",
                    "warnings": _scan_postinst_failures(output),
                })

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._json_response(400, {"error": "invalid JSON"})
            return

        if path == "/os/setup-apt-source":
            # Configure the host to use MonCTL central as its apt mirror.
            # Writes /etc/apt/sources.list.d/monctl.list pointing at the HAProxy VIP,
            # backs up the original sources.list, and runs apt-get update.
            central_vip = payload.get("central_vip", "10.145.210.40")
            distro = payload.get("distro", "noble")
            components = payload.get("components", "main restricted universe multiverse")
            script = f"""set -e
# Backup original sources once
if [ -f /etc/apt/sources.list ] && [ ! -f /etc/apt/sources.list.monctl.bak ]; then
    cp /etc/apt/sources.list /etc/apt/sources.list.monctl.bak
fi
if [ -f /etc/apt/sources.list.d/ubuntu.sources ] && [ ! -f /etc/apt/sources.list.d/ubuntu.sources.monctl.bak ]; then
    cp /etc/apt/sources.list.d/ubuntu.sources /etc/apt/sources.list.d/ubuntu.sources.monctl.bak
fi
# Disable legacy sources.list and the Ubuntu 24.04 deb822 ubuntu.sources
cat > /etc/apt/sources.list <<'EOF'
# Original sources backed up to /etc/apt/sources.list.monctl.bak
# MonCTL apt proxy is used instead — see /etc/apt/sources.list.d/monctl.list
EOF
if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then
    rm -f /etc/apt/sources.list.d/ubuntu.sources
fi
# Write monctl apt source
cat > /etc/apt/sources.list.d/monctl.list <<'EOF'
deb https://{central_vip}/apt/ubuntu {distro} {components}
deb https://{central_vip}/apt/ubuntu {distro}-updates {components}
deb https://{central_vip}/apt/security {distro}-security {components}
EOF
# Trust the HAProxy self-signed cert (pragmatic default — can be upgraded to proper CA trust)
cat > /etc/apt/apt.conf.d/99-monctl <<'EOF'
Acquire::https::Verify-Peer "false";
Acquire::https::Verify-Host "false";
EOF
# Clean up old archive-based os-packages directory if it exists
rm -rf /opt/monctl/os-packages
# Refresh package lists through the new source
apt-get update 2>&1
"""
            try:
                result = _host_exec(script, timeout=120)
                # If apt-get update failed, restore the backup
                if result.returncode != 0:
                    _host_exec(
                        "if [ -f /etc/apt/sources.list.monctl.bak ]; then "
                        "cp /etc/apt/sources.list.monctl.bak /etc/apt/sources.list; fi; "
                        "rm -f /etc/apt/sources.list.d/monctl.list /etc/apt/apt.conf.d/99-monctl",
                        timeout=10,
                    )
                self._json_response(200, {
                    "output": result.stdout[-2000:],
                    "success": result.returncode == 0,
                    "central_vip": central_vip,
                })
            except subprocess.TimeoutExpired:
                self._json_response(500, {"output": "Timeout", "success": False})
            return

        if path == "/os/install":
            packages = payload.get("packages", [])
            if not packages:
                self._json_response(400, {"error": "packages list required"})
                return
            # Sanitize package names
            for pkg in packages:
                if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9.+\-:]*$', pkg):
                    self._json_response(400, {"error": f"invalid package name: {pkg}"})
                    return

            # Launch apt under systemd-run so the install survives the sidecar
            # dying mid-stream. Critical for packages that restart dockerd
            # (docker-ce) or the sidecar's own Python base — without this,
            # dockerd restart kills this container, which kills the nsenter
            # child, leaving apt half-way through postinsts.
            #
            # Pipeline per job:
            #   1. dpkg --configure -a (heals prior interrupted state).
            #   2. apt-get install -y <packages>.
            #   3. Write exit code to /var/run/monctl-apt-<id>.rc.
            #
            # Caller polls /os/install/status?job_id=<id> and survives any
            # sidecar restart in between.
            job_id = secrets.token_hex(6)
            log_path = f"/var/run/monctl-apt-{job_id}.log"
            rc_path = f"/var/run/monctl-apt-{job_id}.rc"
            pkg_str = " ".join(shlex.quote(p) for p in packages)
            inner = (
                f"( DEBIAN_FRONTEND=noninteractive dpkg --configure -a 2>&1; "
                f"  DEBIAN_FRONTEND=noninteractive apt-get install -y {pkg_str} 2>&1 ) "
                f"> {log_path} 2>&1; echo $? > {rc_path}"
            )
            # --collect removes the transient unit on failure. --no-block
            # returns immediately. Unit name is unique per job.
            launch_cmd = (
                f"systemd-run --unit=monctl-apt-{job_id} --collect --no-block "
                f"--property=Type=oneshot "
                f"bash -c {shlex.quote(inner)}"
            )
            launch = _host_exec(launch_cmd, timeout=30)
            if launch.returncode != 0:
                self._json_response(500, {
                    "error": "failed to launch systemd-run",
                    "stderr": launch.stderr,
                    "stdout": launch.stdout,
                })
                return
            self._json_response(202, {
                "job_id": job_id,
                "unit": f"monctl-apt-{job_id}",
                "log_path": log_path,
                "rc_path": rc_path,
            })

        elif path == "/os/reboot":
            delay = payload.get("delay_seconds", 3)
            delay = max(1, min(int(delay), 60))
            try:
                # Fire-and-forget via nsenter into host namespaces so
                # `shutdown` talks to the real systemd on the host.
                subprocess.Popen(
                    [
                        "nsenter",
                        "--target", "1",
                        "--mount", "--uts", "--ipc", "--net", "--pid",
                        "--",
                        "bash", "-c", f"sleep {delay} && shutdown -r now",
                    ],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                self._json_response(200, {
                    "success": True,
                    "message": f"Reboot initiated (delay={delay}s)",
                })
            except Exception as e:
                self._json_response(500, {"success": False, "message": str(e)})

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


# ── Push loop (worker → central) ────────────────────────────────────────────

def _build_system_payload() -> dict:
    """Build /system response payload without HTTP overhead."""
    info = client.info()
    load_avg = None
    cpu_count = info.get("NCPU", 1)
    try:
        with open("/host_root/proc/loadavg") as f:
            parts = f.read().split()
            load_avg = {"1m": float(parts[0]), "5m": float(parts[1]), "15m": float(parts[2])}
    except Exception:
        pass

    mem = {}
    try:
        with open("/host_root/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                key = parts[0].rstrip(":")
                if key in ("MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached",
                           "SwapTotal", "SwapFree"):
                    mem[key] = int(parts[1]) * 1024
    except Exception:
        pass

    uptime_seconds = None
    try:
        with open("/host_root/proc/uptime") as f:
            uptime_seconds = float(f.read().split()[0])
    except Exception:
        pass

    disk = shutil.disk_usage("/host_root") if os.path.exists("/host_root") else None
    ntp = _collect_ntp_status()

    return {
        "hostname": HOSTNAME,
        "docker": {
            "version": info.get("ServerVersion", ""),
            "api_version": info.get("ApiVersion", ""),
            "storage_driver": info.get("Driver", ""),
            "os": info.get("OperatingSystem", ""),
            "kernel": info.get("KernelVersion", ""),
            "architecture": info.get("Architecture", ""),
            "cpus": cpu_count,
            "memory_bytes": info.get("MemTotal", 0),
        },
        "host": {
            "load_avg": load_avg,
            "cpu_count": cpu_count,
            "mem_total_bytes": mem.get("MemTotal"),
            "mem_available_bytes": mem.get("MemAvailable"),
            "mem_free_bytes": mem.get("MemFree"),
            "mem_buffers_bytes": mem.get("Buffers"),
            "mem_cached_bytes": mem.get("Cached"),
            "swap_total_bytes": mem.get("SwapTotal"),
            "swap_free_bytes": mem.get("SwapFree"),
            "uptime_seconds": uptime_seconds,
            "ntp": ntp,
            "disk_total_bytes": disk.total if disk else None,
            "disk_used_bytes": disk.used if disk else None,
            "disk_free_bytes": disk.free if disk else None,
        },
        "containers": {
            "running": info.get("ContainersRunning", 0),
            "paused": info.get("ContainersPaused", 0),
            "stopped": info.get("ContainersStopped", 0),
            "total": info.get("Containers", 0),
        },
    }


def _build_images_payload() -> dict:
    """Build /images response payload without HTTP overhead."""
    images = []
    for img in client.images.list(all=True):
        tags = img.tags or []
        images.append({
            "id": img.short_id, "tags": tags,
            "size_bytes": img.attrs.get("Size", 0),
            "created": img.attrs.get("Created", ""),
            "dangling": len(tags) == 0,
        })

    volumes = []
    for vol in client.volumes.list():
        volumes.append({
            "name": vol.name, "driver": vol.attrs.get("Driver", ""),
            "mountpoint": vol.attrs.get("Mountpoint", ""),
            "created": vol.attrs.get("CreatedAt", ""),
        })

    try:
        df = client.df()
        space_summary = {
            "images_total_bytes": sum(i.get("Size", 0) for i in df.get("Images", [])),
            "images_reclaimable_bytes": sum(
                i.get("Size", 0) for i in df.get("Images", []) if i.get("Containers", 0) == 0
            ),
            "volumes_total_bytes": sum(
                v.get("UsageData", {}).get("Size", 0) for v in df.get("Volumes", [])
            ),
            "build_cache_bytes": sum(b.get("Size", 0) for b in df.get("BuildCache", [])),
        }
    except Exception:
        space_summary = None

    return {
        "images": sorted(images, key=lambda i: i["size_bytes"], reverse=True),
        "volumes": sorted(volumes, key=lambda v: v["name"]),
        "space_summary": space_summary,
        "image_count": len(images),
        "dangling_count": sum(1 for i in images if i["dangling"]),
        "volume_count": len(volumes),
    }


def _push_loop():
    """Background thread: push consolidated payload to central VIP."""
    ssl_ctx = None
    if not PUSH_VERIFY_SSL:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    _last_event_time = 0.0
    _last_log_counts: dict[str, int] = {}  # container → last pushed deque length
    _cycle = 0

    print(f"Push mode enabled → {PUSH_URL} (interval={PUSH_INTERVAL}s, verify_ssl={PUSH_VERIFY_SSL})")

    while True:
        time.sleep(PUSH_INTERVAL)
        _cycle += 1
        try:
            # Stats (from cached collector data)
            with _cached_stats_lock:
                stats = _cached_stats.copy() if _cached_stats else {}

            # System info
            system = _build_system_payload()

            # Logs: only new lines since last push
            logs: dict[str, list] = {}
            with _log_lock:
                for name, buf in _log_buffers.items():
                    current_len = len(buf)
                    prev_len = _last_log_counts.get(name, 0)
                    if current_len > prev_len:
                        # Get new lines (deque grew since last push)
                        new_lines = list(buf)[prev_len:]
                        logs[name] = new_lines
                    elif current_len < prev_len:
                        # Buffer wrapped or container restarted — send all
                        logs[name] = list(buf)
                    _last_log_counts[name] = current_len

            # Events: only new since last push
            with _event_lock:
                events = [e for e in _event_buffer if e["time"] > _last_event_time]
                if _event_buffer:
                    _last_event_time = _event_buffer[-1]["time"]

            # Images: every 4th cycle (60s)
            images = _build_images_payload() if _cycle % 4 == 1 else None

            payload = {
                "host_label": HOSTNAME,
                "timestamp": time.time(),
                "stats": stats,
                "system": system,
                "logs": logs,
                "events": events,
                "images": images,
            }

            data = json.dumps(payload).encode()
            req = Request(PUSH_URL, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {PUSH_API_KEY}")

            resp = urlopen(req, timeout=10, context=ssl_ctx)
            resp.read()

        except URLError as e:
            print(f"Push failed: {e.reason}")
        except Exception as e:
            print(f"Push error: {e}")


def _apt_gc_loop():
    """Hourly sweep of stale /var/run/monctl-apt-* files."""
    while True:
        _gc_apt_job_files()
        time.sleep(3600)


if __name__ == "__main__":
    print(f"Docker stats sidecar starting (host={HOSTNAME}, interval={COLLECT_INTERVAL}s)")
    _cached_stats = _collect_stats()
    print(f"Initial collection done: {_cached_stats['container_count']} running containers")

    # Startup sweep — don't keep apt job files from previous boots.
    _gc_apt_job_files()

    threading.Thread(target=_background_collector, daemon=True).start()
    threading.Thread(target=_log_collector, daemon=True).start()
    threading.Thread(target=_event_listener, daemon=True).start()
    threading.Thread(target=_apt_gc_loop, daemon=True).start()
    if PUSH_URL:
        threading.Thread(target=_push_loop, daemon=True).start()

    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    server = ThreadedHTTPServer(("0.0.0.0", 9100), StatsHandler)
    print("Listening on :9100")
    server.serve_forever()
