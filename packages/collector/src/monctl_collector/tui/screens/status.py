"""Tab 2 — Collector Status screen (Docker, Gossip, System)."""

from __future__ import annotations

import os
import subprocess

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static, DataTable
from textual.timer import Timer


class StatusTab(Vertical):
    """Auto-refreshing status: Docker containers, gossip membership, system stats."""

    DEFAULT_CSS = """
    StatusTab {
        padding: 1 2;
    }
    StatusTab .section-title {
        text-style: bold;
        color: $text;
        margin: 1 0 0 0;
    }
    StatusTab DataTable {
        height: auto;
        max-height: 12;
        margin-bottom: 1;
    }
    StatusTab .stat-bar {
        margin: 0 0 0 2;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Static("Docker Containers", classes="section-title")
        yield DataTable(id="docker-table")

        yield Static("Gossip Membership", classes="section-title")
        yield DataTable(id="gossip-table")

        yield Static("System Resources", classes="section-title")
        yield Static("", id="sys-stats")

    def on_mount(self) -> None:
        # Docker table columns
        dt = self.query_one("#docker-table", DataTable)
        dt.add_columns("Name", "Status", "State")

        # Gossip table columns
        gt = self.query_one("#gossip-table", DataTable)
        gt.add_columns("Node ID", "Address", "Status")

        self._refresh_all()
        self._timer = self.set_interval(5.0, self._refresh_all)

    def _refresh_all(self) -> None:
        self._refresh_docker()
        self._refresh_gossip()
        self._refresh_system()

    def _refresh_docker(self) -> None:
        dt = self.query_one("#docker-table", DataTable)
        dt.clear()
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.State}}"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 3:
                    dt.add_row(*parts[:3])
                elif len(parts) == 2:
                    dt.add_row(parts[0], parts[1], "")
        except Exception:
            dt.add_row("(docker not available)", "", "")

    def _refresh_gossip(self) -> None:
        gt = self.query_one("#gossip-table", DataTable)
        gt.clear()
        try:
            import httpx
            r = httpx.get("http://127.0.0.1:50052/status", timeout=2.0)
            data = r.json()
            for member in data.get("membership", []):
                gt.add_row(
                    member.get("node_id", ""),
                    member.get("address", ""),
                    member.get("status", ""),
                )
        except Exception:
            gt.add_row("(gossip not available)", "", "")

    def _refresh_system(self) -> None:
        stats = self.query_one("#sys-stats", Static)
        lines: list[str] = []

        # CPU
        try:
            with open("/proc/loadavg") as f:
                load = f.read().split()[:3]
            cpu_count = os.cpu_count() or 1
            lines.append(f"Load: {' '.join(load)}  (CPUs: {cpu_count})")
        except Exception:
            lines.append("CPU: N/A")

        # Memory
        try:
            with open("/proc/meminfo") as f:
                mem = {}
                for line in f:
                    parts = line.split()
                    if parts[0] in ("MemTotal:", "MemAvailable:", "MemFree:"):
                        mem[parts[0].rstrip(":")] = int(parts[1])
            total_mb = mem.get("MemTotal", 0) / 1024
            avail_mb = mem.get("MemAvailable", mem.get("MemFree", 0)) / 1024
            used_mb = total_mb - avail_mb
            pct = (used_mb / total_mb * 100) if total_mb > 0 else 0
            bar = self._progress_bar(pct)
            lines.append(f"RAM:  {bar} {used_mb:.0f}/{total_mb:.0f} MB ({pct:.0f}%)")
        except Exception:
            lines.append("RAM: N/A")

        # Disk
        try:
            st = os.statvfs("/")
            total = st.f_blocks * st.f_frsize / (1024**3)
            free = st.f_bfree * st.f_frsize / (1024**3)
            used = total - free
            pct = (used / total * 100) if total > 0 else 0
            bar = self._progress_bar(pct)
            lines.append(f"Disk: {bar} {used:.1f}/{total:.1f} GB ({pct:.0f}%)")
        except Exception:
            lines.append("Disk: N/A")

        stats.update("\n".join(lines))

    @staticmethod
    def _progress_bar(pct: float, width: int = 20) -> str:
        filled = int(width * pct / 100)
        return f"[{'█' * filled}{'░' * (width - filled)}]"
