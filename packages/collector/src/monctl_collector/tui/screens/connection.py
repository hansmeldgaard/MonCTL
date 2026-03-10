"""Tab 3 — Central Connection screen (register, poll status, write .env)."""

from __future__ import annotations

import os
import socket
import subprocess

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Static, Input, Button, Label
from textual.timer import Timer

from monctl_collector.tui.central_client import CentralClient
from monctl_collector.tui.fingerprint import generate_fingerprint
from monctl_collector.tui.state import SetupState


_ENV_PATH = "/opt/monctl/collector/.env"


class ConnectionTab(Vertical):
    """Central connection — register, poll approval, write .env on activation."""

    DEFAULT_CSS = """
    ConnectionTab {
        padding: 1 2;
    }
    ConnectionTab .section-title {
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }
    ConnectionTab .fingerprint-box {
        background: $surface;
        padding: 1 2;
        margin-bottom: 1;
        text-style: bold;
        color: $text;
    }
    ConnectionTab .field-row {
        height: 3;
        margin-bottom: 0;
    }
    ConnectionTab .field-label {
        width: 18;
        padding-top: 1;
        color: $text-muted;
    }
    ConnectionTab Input {
        width: 1fr;
    }
    ConnectionTab .button-row {
        margin-top: 1;
        height: 3;
    }
    ConnectionTab .status-label {
        margin-top: 1;
        padding: 0 1;
    }
    ConnectionTab .status-pending {
        color: $warning;
    }
    ConnectionTab .status-active {
        color: $success;
    }
    ConnectionTab .status-rejected {
        color: $error;
    }
    ConnectionTab .status-none {
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._state = SetupState.load()
        self._fingerprint = self._state.fingerprint or generate_fingerprint()
        self._poll_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Static("Central Connection", classes="section-title")

        yield Static("Machine Fingerprint", classes="section-title")
        yield Static(self._fingerprint, id="fingerprint-display", classes="fingerprint-box")

        with Horizontal(classes="field-row"):
            yield Label("Central URL", classes="field-label")
            yield Input(
                id="conn-url",
                placeholder="http://192.168.1.122:8443",
                value=self._state.central_url,
            )
        with Horizontal(classes="field-row"):
            yield Label("Registration Code", classes="field-label")
            yield Input(id="conn-token", placeholder="A3X9K2", max_length=8)

        with Horizontal(classes="button-row"):
            yield Button("Test Connection", id="conn-test", variant="default")
            yield Button("Register", id="conn-register", variant="primary")

        yield Static("", id="conn-status", classes="status-label status-none")
        yield Static("", id="reg-status", classes="status-label status-none")

    def on_mount(self) -> None:
        # If already registered, start polling or fetch current status
        if self._state.collector_id and self._state.api_key:
            self._update_conn_status(f"Registered as {self._state.collector_id[:8]}...")
            if self._state.status == "PENDING":
                self._start_polling()
            elif self._state.status == "ACTIVE":
                self._show_reg_status("ACTIVE", "Approved and active")
                # Fetch group info from central
                self.run_worker(self._fetch_active_status, thread=True)
            self.query_one("#conn-url", Input).value = self._state.central_url

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "conn-test":
            self._test_connection()
        elif event.button.id == "conn-register":
            self._register()

    def _test_connection(self) -> None:
        """Test connectivity to central."""
        url = self.query_one("#conn-url", Input).value.strip()
        if not url:
            self._update_conn_status("Enter a Central URL first", error=True)
            return

        self._update_conn_status("Testing connection...")
        self._test_url = url
        self.run_worker(self._do_test, thread=True)

    def _do_test(self) -> None:
        url = self._test_url
        try:
            client = CentralClient(url)
            result = client.health()
            self.app.call_from_thread(
                self._update_conn_status,
                f"Connected — version {result.get('version', 'unknown')}",
            )
        except Exception as e:
            self.app.call_from_thread(
                self._update_conn_status, f"Connection failed: {e}", error=True
            )

    def _register(self) -> None:
        """Register this collector with central."""
        url = self.query_one("#conn-url", Input).value.strip()
        token = self.query_one("#conn-token", Input).value.strip()

        if not url:
            self._update_conn_status("Enter a Central URL first", error=True)
            return
        if not token:
            self._update_conn_status("Enter a registration code", error=True)
            return

        self._update_conn_status("Registering...")
        self._reg_url = url
        self._reg_token = token
        self.run_worker(self._do_register, thread=True)

    def _do_register(self) -> None:
        url = self._reg_url
        token = self._reg_token
        try:
            hostname = socket.gethostname()
            ip_addresses = self._get_local_ips()

            client = CentralClient(url)
            result = client.register(
                hostname=hostname,
                registration_code=token.strip().upper(),
                fingerprint=self._fingerprint,
                ip_addresses=ip_addresses,
            )

            # Save state
            self._state.central_url = url
            self._state.collector_id = result["collector_id"]
            self._state.api_key = result["api_key"]
            self._state.fingerprint = self._fingerprint
            self._state.status = result.get("status", "PENDING")
            self._state.save()

            self.app.call_from_thread(
                self._update_conn_status,
                f"Registered as {result['collector_id'][:8]}... — waiting for approval",
            )
            self.app.call_from_thread(
                self._show_reg_status, "PENDING", "Waiting for admin approval"
            )
            self.app.call_from_thread(self._start_polling)

        except Exception as e:
            self.app.call_from_thread(
                self._update_conn_status, f"Registration failed: {e}", error=True
            )

    def _start_polling(self) -> None:
        """Poll registration status every 10s."""
        if self._poll_timer:
            return
        self._poll_timer = self.set_interval(10.0, self._poll_status)

    def _poll_status(self) -> None:
        """Check registration status."""
        if not self._state.collector_id or not self._state.api_key:
            return
        self.run_worker(self._do_poll, thread=True)

    def _do_poll(self) -> None:
        try:
            client = CentralClient(self._state.central_url, api_key=self._state.api_key)
            result = client.registration_status(self._state.collector_id)
            status = result.get("status", "")

            if status == "ACTIVE":
                self._state.status = "ACTIVE"
                self._state.save()

                group_name = result.get("group_name", "")
                msg = f"Approved — Group: {group_name}" if group_name else "Approved"
                self.app.call_from_thread(self._show_reg_status, "ACTIVE", msg)
                self.app.call_from_thread(self._update_conn_status, "Collector is ACTIVE")
                self.app.call_from_thread(self._write_env_and_offer_restart)

                # Stop polling
                if self._poll_timer:
                    self._poll_timer.stop()
                    self._poll_timer = None

            elif status == "REJECTED":
                self._state.status = "REJECTED"
                self._state.save()

                reason = result.get("rejected_reason", "No reason given")
                self.app.call_from_thread(
                    self._show_reg_status, "REJECTED", f"Rejected: {reason}"
                )
                if self._poll_timer:
                    self._poll_timer.stop()
                    self._poll_timer = None

        except Exception:
            pass  # Silently retry next cycle

    def _fetch_active_status(self) -> None:
        """Fetch current registration status from central to show group info."""
        try:
            client = CentralClient(self._state.central_url, api_key=self._state.api_key)
            result = client.registration_status(self._state.collector_id)
            status = result.get("status", "ACTIVE")

            if status == "ACTIVE":
                group_name = result.get("group_name", "")
                if group_name:
                    msg = f"Approved — Group: {group_name}"
                else:
                    msg = "Approved — No group assigned"
                self.app.call_from_thread(self._show_reg_status, status, msg)
            elif status == "REJECTED":
                reason = result.get("rejected_reason", "No reason given")
                self._state.status = "REJECTED"
                self._state.save()
                self.app.call_from_thread(
                    self._show_reg_status, "REJECTED", f"Rejected: {reason}"
                )
            elif status == "PENDING":
                self._state.status = "PENDING"
                self._state.save()
                self.app.call_from_thread(
                    self._show_reg_status, "PENDING", "Waiting for admin approval"
                )
                self.app.call_from_thread(self._start_polling)
        except Exception as exc:
            # 401/403/404 = collector deleted or API key revoked
            err_str = str(exc)
            if any(code in err_str for code in ("401", "403", "404")):
                self._state.status = "REMOVED"
                self._state.collector_id = ""
                self._state.api_key = ""
                self._state.save()
                self.app.call_from_thread(
                    self._show_reg_status,
                    "REJECTED",
                    "Collector removed from central — re-register to reconnect",
                )
                self.app.call_from_thread(
                    self._update_conn_status, "Collector no longer exists on central"
                )

    def _update_conn_status(self, msg: str, error: bool = False) -> None:
        status = self.query_one("#conn-status", Static)
        status.update(msg)
        status.set_classes(f"status-label {'status-rejected' if error else 'status-none'}")

    def _show_reg_status(self, state: str, msg: str) -> None:
        status = self.query_one("#reg-status", Static)
        cls_map = {
            "PENDING": "status-pending",
            "ACTIVE": "status-active",
            "REJECTED": "status-rejected",
        }
        status.update(f"Registration: {msg}")
        status.set_classes(f"status-label {cls_map.get(state, 'status-none')}")

    def _write_env_and_offer_restart(self) -> None:
        """Write CENTRAL_URL + API_KEY to .env and offer to restart Docker services."""
        try:
            env_dir = os.path.dirname(_ENV_PATH)
            os.makedirs(env_dir, exist_ok=True)

            # Read existing .env and update/add our keys
            existing: dict[str, str] = {}
            if os.path.exists(_ENV_PATH):
                with open(_ENV_PATH) as f:
                    for line in f:
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            k, v = line.split("=", 1)
                            existing[k] = v

            existing["MONCTL_CENTRAL_URL"] = self._state.central_url
            existing["MONCTL_CENTRAL_API_KEY"] = self._state.api_key

            with open(_ENV_PATH, "w") as f:
                for k, v in existing.items():
                    f.write(f"{k}={v}\n")
            os.chmod(_ENV_PATH, 0o600)

            self._update_conn_status(
                f"Wrote credentials to {_ENV_PATH} — restarting Docker services..."
            )

            # Restart collector Docker services
            try:
                compose_dir = "/opt/monctl/collector"
                compose_file = os.path.join(compose_dir, "docker-compose.yml")
                if os.path.exists(compose_file):
                    result = subprocess.run(
                        ["docker", "compose", "-f", compose_file, "restart"],
                        capture_output=True, text=True, timeout=60,
                        cwd=compose_dir,
                    )
                    if result.returncode == 0:
                        self._update_conn_status("Credentials saved and Docker services restarted")
                    else:
                        self._update_conn_status(
                            f"Credentials saved but restart failed: {result.stderr.strip()}",
                            error=True,
                        )
                else:
                    self._update_conn_status(
                        f"Credentials saved — no compose file found at {compose_file}"
                    )
            except Exception as e:
                self._update_conn_status(
                    f"Credentials saved but restart failed: {e}", error=True
                )
        except Exception as e:
            self._update_conn_status(f"Could not write .env: {e}", error=True)

    @staticmethod
    def _get_local_ips() -> list[str]:
        """Get local IP addresses (non-loopback)."""
        ips: list[str] = []
        try:
            result = subprocess.run(
                ["hostname", "-I"], capture_output=True, text=True, timeout=5
            )
            ips = result.stdout.strip().split()
        except Exception:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                ips = [s.getsockname()[0]]
                s.close()
            except Exception:
                pass
        return ips
