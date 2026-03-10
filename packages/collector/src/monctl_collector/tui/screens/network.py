"""Tab 1 — Network Configuration screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Static, Input, RadioButton, RadioSet, Button, Label
from textual.worker import Worker, WorkerState

from monctl_collector.tui.network.common import NetworkConfig
from monctl_collector.tui.network.detect import detect_backend, detect_interface, get_current_ip


class NetworkTab(Vertical):
    """Network configuration tab with DHCP/Static toggle and fields."""

    DEFAULT_CSS = """
    NetworkTab {
        padding: 1 2;
    }
    NetworkTab .section-title {
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }
    NetworkTab .field-row {
        height: 3;
        margin-bottom: 0;
    }
    NetworkTab .field-label {
        width: 14;
        padding-top: 1;
        color: $text-muted;
    }
    NetworkTab Input {
        width: 1fr;
    }
    NetworkTab .status-msg {
        margin-top: 1;
        color: $success;
    }
    NetworkTab .error-msg {
        margin-top: 1;
        color: $error;
    }
    NetworkTab .button-row {
        margin-top: 1;
        height: 3;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._backend = detect_backend()
        self._interface = detect_interface()
        self._config = NetworkConfig(interface=self._interface)

    def compose(self) -> ComposeResult:
        yield Static(f"Network Configuration ({self._backend})", classes="section-title")
        yield Static(f"Interface: {self._interface}", id="net-interface")

        with Horizontal(classes="field-row"):
            yield Label("Mode", classes="field-label")
            with RadioSet(id="net-mode"):
                yield RadioButton("DHCP", value=True, id="mode-dhcp")
                yield RadioButton("Static", id="mode-static")

        with Horizontal(classes="field-row"):
            yield Label("IP Address", classes="field-label")
            yield Input(id="net-ip", placeholder="192.168.1.10")
        with Horizontal(classes="field-row"):
            yield Label("Subnet (/xx)", classes="field-label")
            yield Input(id="net-subnet", placeholder="24")
        with Horizontal(classes="field-row"):
            yield Label("Gateway", classes="field-label")
            yield Input(id="net-gateway", placeholder="192.168.1.1")
        with Horizontal(classes="field-row"):
            yield Label("DNS 1", classes="field-label")
            yield Input(id="net-dns1", placeholder="8.8.8.8")
        with Horizontal(classes="field-row"):
            yield Label("DNS 2", classes="field-label")
            yield Input(id="net-dns2", placeholder="8.8.4.4")
        with Horizontal(classes="field-row"):
            yield Label("NTP 1", classes="field-label")
            yield Input(id="net-ntp1", placeholder="pool.ntp.org")
        with Horizontal(classes="field-row"):
            yield Label("NTP 2", classes="field-label")
            yield Input(id="net-ntp2", placeholder="")
        with Horizontal(classes="field-row"):
            yield Label("Proxy", classes="field-label")
            yield Input(id="net-proxy", placeholder="http://proxy:3128")

        with Horizontal(classes="button-row"):
            yield Button("Apply", id="net-apply", variant="primary")
            yield Button("Revert", id="net-revert", variant="warning")

        yield Static("", id="net-status")

    def on_mount(self) -> None:
        """Load current values from system."""
        self._load_current()

    def _load_current(self) -> None:
        """Read current network config and populate fields."""
        # Read from backend
        if self._backend == "netplan":
            from monctl_collector.tui.network.netplan import read_config
            self._config = read_config(self._interface)
        elif self._backend == "interfaces":
            from monctl_collector.tui.network.interfaces import read_config
            self._config = read_config(self._interface)
        else:
            # Fall back to reading from system directly
            sys_info = get_current_ip(self._interface)
            self._config = NetworkConfig(
                interface=self._interface,
                ip_address=sys_info.get("ip_address", ""),
                subnet_mask=sys_info.get("subnet_mask", "24"),
                gateway=sys_info.get("gateway", ""),
                dns1=sys_info.get("dns1", ""),
                dns2=sys_info.get("dns2", ""),
            )

        # Populate UI fields
        self._update_fields()

    def _update_fields(self) -> None:
        """Sync config to UI."""
        try:
            self.query_one("#net-ip", Input).value = self._config.ip_address
            self.query_one("#net-subnet", Input).value = self._config.subnet_mask
            self.query_one("#net-gateway", Input).value = self._config.gateway
            self.query_one("#net-dns1", Input).value = self._config.dns1
            self.query_one("#net-dns2", Input).value = self._config.dns2
            self.query_one("#net-ntp1", Input).value = self._config.ntp1
            self.query_one("#net-ntp2", Input).value = self._config.ntp2
            self.query_one("#net-proxy", Input).value = self._config.proxy

            mode_set = self.query_one("#net-mode", RadioSet)
            if self._config.dhcp:
                mode_set.query_one("#mode-dhcp", RadioButton).value = True
            else:
                mode_set.query_one("#mode-static", RadioButton).value = True

            self._toggle_static_fields(not self._config.dhcp)
        except Exception:
            pass

    def _toggle_static_fields(self, enabled: bool) -> None:
        """Enable/disable static IP fields."""
        for fid in ("net-ip", "net-subnet", "net-gateway"):
            try:
                self.query_one(f"#{fid}", Input).disabled = not enabled
            except Exception:
                pass

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "net-mode":
            is_static = event.pressed.id == "mode-static"
            self._toggle_static_fields(is_static)

    def _read_fields(self) -> NetworkConfig:
        """Read current values from UI inputs."""
        mode_set = self.query_one("#net-mode", RadioSet)
        is_dhcp = mode_set.pressed_button.id == "mode-dhcp" if mode_set.pressed_button else True

        return NetworkConfig(
            interface=self._interface,
            dhcp=is_dhcp,
            ip_address=self.query_one("#net-ip", Input).value.strip(),
            subnet_mask=self.query_one("#net-subnet", Input).value.strip(),
            gateway=self.query_one("#net-gateway", Input).value.strip(),
            dns1=self.query_one("#net-dns1", Input).value.strip(),
            dns2=self.query_one("#net-dns2", Input).value.strip(),
            ntp1=self.query_one("#net-ntp1", Input).value.strip(),
            ntp2=self.query_one("#net-ntp2", Input).value.strip(),
            proxy=self.query_one("#net-proxy", Input).value.strip(),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "net-apply":
            self._apply()
        elif event.button.id == "net-revert":
            self._revert()

    def _apply(self) -> None:
        """Validate and apply network configuration."""
        cfg = self._read_fields()
        errors = cfg.validate()
        status = self.query_one("#net-status", Static)

        if errors:
            status.update("\n".join(errors))
            status.set_classes("error-msg")
            return

        # Write and apply
        try:
            if self._backend == "netplan":
                from monctl_collector.tui.network.netplan import write_config, apply_config
            elif self._backend == "interfaces":
                from monctl_collector.tui.network.interfaces import write_config, apply_config
            else:
                status.update("Unknown network backend — cannot apply")
                status.set_classes("error-msg")
                return

            msg = write_config(cfg)
            result = apply_config()
            status.update(f"{msg}\n{result}")
            status.set_classes("status-msg")
        except Exception as e:
            status.update(f"Error: {e}")
            status.set_classes("error-msg")

    def _revert(self) -> None:
        """Revert to backup configuration."""
        status = self.query_one("#net-status", Static)
        try:
            if self._backend == "netplan":
                from monctl_collector.tui.network.netplan import revert_config
            elif self._backend == "interfaces":
                from monctl_collector.tui.network.interfaces import revert_config
            else:
                status.update("Unknown backend — cannot revert")
                status.set_classes("error-msg")
                return

            result = revert_config()
            status.update(result)
            status.set_classes("status-msg")
            self._load_current()
        except Exception as e:
            status.update(f"Error: {e}")
            status.set_classes("error-msg")
