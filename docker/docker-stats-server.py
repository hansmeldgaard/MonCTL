"""Lightweight Docker stats sidecar for MonCTL.

Collects container stats in a background thread every 15 seconds.
Serves cached results instantly on GET /stats.
Also provides /logs, /events, /images, /system endpoints.
"""

import json
import os
import shutil
import socket
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import docker

client = docker.from_env()
HOSTNAME = os.environ.get("MONCTL_HOST_LABEL", socket.gethostname())
COLLECT_INTERVAL = int(os.environ.get("COLLECT_INTERVAL", "15"))

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

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    print(f"Docker stats sidecar starting (host={HOSTNAME}, interval={COLLECT_INTERVAL}s)")
    _cached_stats = _collect_stats()
    print(f"Initial collection done: {_cached_stats['container_count']} running containers")

    threading.Thread(target=_background_collector, daemon=True).start()
    threading.Thread(target=_log_collector, daemon=True).start()
    threading.Thread(target=_event_listener, daemon=True).start()

    server = HTTPServer(("0.0.0.0", 9100), StatsHandler)
    print("Listening on :9100")
    server.serve_forever()
