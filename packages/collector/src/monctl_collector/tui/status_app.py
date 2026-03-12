"""monctl-status — Standalone Textual TUI for collector status monitoring."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from monctl_collector.tui.screens.status import StatusTab

CSS_PATH = Path(__file__).parent / "app.tcss"


class MonctlStatusApp(App):
    """MonCTL Collector Status — Docker, Gossip, System stats."""

    TITLE = "monctl-status"
    CSS_PATH = CSS_PATH
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield StatusTab()
        yield Footer()

    def action_refresh(self) -> None:
        self.query_one(StatusTab)._refresh_all()


def main() -> None:
    app = MonctlStatusApp()
    app.run()


if __name__ == "__main__":
    main()
