"""Lightweight Docker stats sidecar for MonCTL.

Collects container stats in a background thread every 15 seconds.
Serves cached results instantly on GET /stats.
Also provides /logs, /events, /images, /system endpoints.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
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
PUSH_VERIFY_SSL = os.environ.get("MONCTL_PUSH_VERIFY_SSL", "false").lower() in ("true", "1", "yes")

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

        elif path == "/os/check":
            try:
                params = _parse_qs_single(self.path)
                proxy_url = params.get("proxy_url", "")
                proxy_env = f"http_proxy={proxy_url} https_proxy={proxy_url} " if proxy_url else ""
                result = subprocess.run(
                    ["chroot", "/host_root", "bash", "-c",
                     f"{proxy_env}apt-get update -qq 2>/dev/null && apt list --upgradable 2>/dev/null"],
                    capture_output=True, text=True, timeout=120,
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

        elif path == "/os/reboot-required":
            reboot_file = "/host_root/var/run/reboot-required"
            pkgs_file = "/host_root/var/run/reboot-required.pkgs"
            required = os.path.isfile(reboot_file)
            packages = []
            if required and os.path.isfile(pkgs_file):
                try:
                    with open(pkgs_file) as f:
                        packages = [line.strip() for line in f if line.strip()]
                except Exception:
                    pass
            self._json_response(200, {
                "reboot_required": required,
                "packages": packages,
            })

        elif path == "/os/installed":
            try:
                result = subprocess.run(
                    ["chroot", "/host_root", "dpkg-query", "-W",
                     "-f", "${Package}\t${Version}\t${Architecture}\t${Status}\n"],
                    capture_output=True, text=True, timeout=30,
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

        elif path.startswith("/os/packages/"):
            filename = path[len("/os/packages/"):]
            # Sanitize: no path traversal
            if not filename or "/" in filename or "\\" in filename or ".." in filename:
                self._json_response(400, {"error": "invalid filename"})
                return
            filepath = f"/host_root/opt/monctl/os-packages/{filename}"
            if not os.path.isfile(filepath):
                self._json_response(404, {"error": "file not found"})
                return
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                file_size = os.path.getsize(filepath)
                self.send_header("Content-Length", str(file_size))
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.end_headers()
                with open(filepath, "rb") as f:
                    while chunk := f.read(65536):
                        self.wfile.write(chunk)
            except BrokenPipeError:
                pass

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
            pkg_str = " ".join(packages)
            try:
                result = subprocess.run(
                    ["chroot", "/host_root", "bash", "-c",
                     f"DEBIAN_FRONTEND=noninteractive apt-get install -y {pkg_str} 2>&1"],
                    capture_output=True, text=True, timeout=600,
                )
                self._json_response(200, {
                    "output": result.stdout,
                    "returncode": result.returncode,
                    "success": result.returncode == 0,
                })
            except subprocess.TimeoutExpired:
                self._json_response(500, {"output": "", "returncode": -1, "success": False})

        elif path == "/os/install-deb":
            deb_dir = payload.get("deb_dir", "/opt/monctl/os-packages")
            filenames = payload.get("filenames", [])
            if not filenames:
                self._json_response(400, {"error": "filenames list required"})
                return
            # Sanitize filenames
            for fn in filenames:
                if "/" in fn or "\\" in fn or ".." in fn:
                    self._json_response(400, {"error": f"invalid filename: {fn}"})
                    return
            paths_str = " ".join(f"{deb_dir}/{fn}" for fn in filenames)
            try:
                result = subprocess.run(
                    ["chroot", "/host_root", "bash", "-c",
                     f"dpkg -i {paths_str} 2>&1 && apt-get install -f -y 2>&1"],
                    capture_output=True, text=True, timeout=600,
                )
                self._json_response(200, {
                    "output": result.stdout,
                    "returncode": result.returncode,
                    "success": result.returncode == 0,
                })
            except subprocess.TimeoutExpired:
                self._json_response(500, {"output": "", "returncode": -1, "success": False})

        elif path == "/os/download":
            packages = payload.get("packages", [])
            proxy_url = payload.get("proxy_url", "")
            if not packages:
                self._json_response(400, {"error": "packages list required"})
                return
            for pkg in packages:
                if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9.+\-:]*$', pkg):
                    self._json_response(400, {"error": f"invalid package name: {pkg}"})
                    return
            pkg_str = " ".join(packages)
            proxy_env = f"http_proxy={proxy_url} https_proxy={proxy_url} " if proxy_url else ""
            deb_dir = "/host_root/opt/monctl/os-packages"
            try:
                # Resolve dependencies: find all packages needed (including deps)
                deps_result = subprocess.run(
                    ["chroot", "/host_root", "bash", "-c",
                     f"apt-cache depends --recurse --no-recommends --no-suggests "
                     f"--no-conflicts --no-breaks --no-replaces --no-enhances "
                     f"{pkg_str} 2>/dev/null | grep '^\\w' | sort -u"],
                    capture_output=True, text=True, timeout=30,
                )
                all_pkgs = [p.strip() for p in deps_result.stdout.strip().splitlines() if p.strip()]
                # Filter to only packages that have upgradable versions
                # (avoid downloading already-installed packages)
                if all_pkgs:
                    check = subprocess.run(
                        ["chroot", "/host_root", "bash", "-c",
                         f"apt list --upgradable 2>/dev/null | grep -oP '^[^/]+'"],
                        capture_output=True, text=True, timeout=30,
                    )
                    upgradable = set(check.stdout.strip().splitlines())
                    # Keep original packages + any deps that are upgradable or not installed
                    # Include all deps: upgradable + not-installed-anywhere
                    # Central may have deps installed that workers don't, so
                    # download everything in the dep tree that is either
                    # upgradable or version-specific (contains version numbers)
                    download_pkgs = set(packages)
                    for p in all_pkgs:
                        if p in upgradable:
                            download_pkgs.add(p)
                        # Version-specific packages (e.g. linux-image-6.8.0-107-generic)
                        # are likely needed by workers even if central has them
                        elif any(c.isdigit() for c in p):
                            download_pkgs.add(p)
                    dl_str = " ".join(sorted(download_pkgs))
                else:
                    dl_str = pkg_str

                # Download packages
                result = subprocess.run(
                    ["chroot", "/host_root", "bash", "-c",
                     f"mkdir -p /opt/monctl/os-packages && cd /opt/monctl/os-packages && "
                     f"{proxy_env}apt-get download {dl_str} 2>&1"],
                    capture_output=True, text=True, timeout=300,
                )
                # List .deb files in the directory
                downloaded = []
                if os.path.isdir(deb_dir):
                    for fn in os.listdir(deb_dir):
                        if fn.endswith(".deb"):
                            fpath = os.path.join(deb_dir, fn)
                            downloaded.append({
                                "filename": fn,
                                "size": os.path.getsize(fpath),
                            })
                self._json_response(200, {
                    "downloaded": downloaded,
                    "output": result.stdout,
                    "success": result.returncode == 0,
                    "resolved_packages": dl_str.split(),
                })
            except subprocess.TimeoutExpired:
                self._json_response(500, {"downloaded": [], "output": "", "success": False})

        elif path == "/os/fetch-debs":
            central_url = payload.get("central_url", "")
            api_key = payload.get("api_key", "")
            filenames = payload.get("filenames", [])
            if not filenames or not central_url:
                self._json_response(400, {"error": "central_url and filenames required"})
                return
            for fn in filenames:
                if "/" in fn or "\\" in fn or ".." in fn:
                    self._json_response(400, {"error": f"invalid filename: {fn}"})
                    return
            deb_dir = "/opt/monctl/os-packages"
            fetched = []
            errors = []
            for fn in filenames:
                try:
                    from urllib.parse import quote
                    url = f"{central_url}/api/v1/os-packages/download/{quote(fn, safe='')}"
                    result = subprocess.run(
                        ["chroot", "/host_root", "curl", "-fk",
                         "-H", f"Authorization: Bearer {api_key}",
                         "-o", f"{deb_dir}/{fn}",
                         "--create-dirs", "--path-as-is", url],
                        capture_output=True, text=True, timeout=120,
                    )
                    if result.returncode == 0:
                        fetched.append(fn)
                    else:
                        errors.append(f"{fn}: {result.stderr.strip()}")
                except subprocess.TimeoutExpired:
                    errors.append(f"{fn}: timeout")
            self._json_response(200, {
                "fetched": fetched,
                "errors": errors,
                "success": len(fetched) == len(filenames),
            })

        elif path == "/os/reboot":
            delay = payload.get("delay_seconds", 3)
            delay = max(1, min(int(delay), 60))
            try:
                subprocess.Popen(
                    ["chroot", "/host_root", "bash", "-c",
                     f"sleep {delay} && shutdown -r now"],
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
            logs: dict[str, list[str]] = {}
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


if __name__ == "__main__":
    print(f"Docker stats sidecar starting (host={HOSTNAME}, interval={COLLECT_INTERVAL}s)")
    _cached_stats = _collect_stats()
    print(f"Initial collection done: {_cached_stats['container_count']} running containers")

    threading.Thread(target=_background_collector, daemon=True).start()
    threading.Thread(target=_log_collector, daemon=True).start()
    threading.Thread(target=_event_listener, daemon=True).start()
    if PUSH_URL:
        threading.Thread(target=_push_loop, daemon=True).start()

    server = HTTPServer(("0.0.0.0", 9100), StatsHandler)
    print("Listening on :9100")
    server.serve_forever()
