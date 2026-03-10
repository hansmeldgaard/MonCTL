"""monctl-setup — Textual TUI for collector management.

Run on a collector VM via SSH to configure networking, view status,
and register with the central server.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Static, TabbedContent, TabPane, Footer, Header

from monctl_collector.tui.screens.network import NetworkTab
from monctl_collector.tui.screens.status import StatusTab
from monctl_collector.tui.screens.connection import ConnectionTab

CSS_PATH = Path(__file__).parent / "app.tcss"


class MonctlSetupApp(App):
    """MonCTL Collector Setup — 3-tab TUI."""

    TITLE = "monctl-setup"
    CSS_PATH = CSS_PATH
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("1", "tab_network", "Network"),
        ("2", "tab_status", "Status"),
        ("3", "tab_connection", "Connection"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="tabs"):
            with TabPane("Network", id="tab-network"):
                yield NetworkTab()
            with TabPane("Status", id="tab-status"):
                yield StatusTab()
            with TabPane("Connection", id="tab-connection"):
                yield ConnectionTab()
        yield Footer()

    def on_mount(self) -> None:
        # Warn if not running as root (needed for network changes)
        if os.geteuid() != 0:
            self.notify(
                "Not running as root — network changes will require elevated privileges",
                severity="warning",
                timeout=5,
            )

    def action_tab_network(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-network"

    def action_tab_status(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-status"

    def action_tab_connection(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-connection"


def main() -> None:
    app = MonctlSetupApp()
    app.run()


if __name__ == "__main__":
    main()
