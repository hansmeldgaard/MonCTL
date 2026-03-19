"""Lightweight Docker stats sidecar for MonCTL.

Collects container stats in a background thread every 15 seconds.
Serves cached results instantly on GET /stats.
"""

import json
import os
import shutil
import socket
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

import docker

client = docker.from_env()
HOSTNAME = os.environ.get("MONCTL_HOST_LABEL", socket.gethostname())
COLLECT_INTERVAL = int(os.environ.get("COLLECT_INTERVAL", "15"))

_cached_stats: dict = {}
_cached_stats_lock = threading.Lock()


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
    def do_GET(self):
        if self.path == "/stats":
            try:
                with _cached_stats_lock:
                    data = _cached_stats
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            except BrokenPipeError:
                pass
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    print(f"Docker stats sidecar starting (host={HOSTNAME}, interval={COLLECT_INTERVAL}s)")
    _cached_stats = _collect_stats()
    print(f"Initial collection done: {_cached_stats['container_count']} running containers")

    collector_thread = threading.Thread(target=_background_collector, daemon=True)
    collector_thread.start()

    server = HTTPServer(("0.0.0.0", 9100), StatsHandler)
    print(f"Listening on :9100")
    server.serve_forever()
