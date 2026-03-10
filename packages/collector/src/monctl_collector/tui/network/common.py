"""Network configuration data model and validation."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field


@dataclass
class NetworkConfig:
    interface: str = ""
    dhcp: bool = True
    ip_address: str = ""
    subnet_mask: str = "24"
    gateway: str = ""
    dns1: str = ""
    dns2: str = ""
    ntp1: str = ""
    ntp2: str = ""
    proxy: str = ""

    def validate(self) -> list[str]:
        """Return list of validation errors (empty = valid)."""
        errors: list[str] = []
        if self.dhcp:
            return errors

        if not self.ip_address:
            errors.append("IP address is required for static config")
        else:
            try:
                ipaddress.IPv4Address(self.ip_address)
            except ValueError:
                errors.append(f"Invalid IP address: {self.ip_address}")

        if self.subnet_mask:
            try:
                prefix = int(self.subnet_mask)
                if not (1 <= prefix <= 32):
                    errors.append("Subnet prefix must be between 1 and 32")
            except ValueError:
                errors.append(f"Invalid subnet mask: {self.subnet_mask}")

        if self.gateway:
            try:
                ipaddress.IPv4Address(self.gateway)
            except ValueError:
                errors.append(f"Invalid gateway: {self.gateway}")
            else:
                # Check gateway is in same subnet
                if self.ip_address and self.subnet_mask:
                    try:
                        net = ipaddress.IPv4Network(
                            f"{self.ip_address}/{self.subnet_mask}", strict=False
                        )
                        if ipaddress.IPv4Address(self.gateway) not in net:
                            errors.append("Gateway is not in the same subnet")
                    except ValueError:
                        pass

        for label, val in [("DNS 1", self.dns1), ("DNS 2", self.dns2)]:
            if val:
                try:
                    ipaddress.IPv4Address(val)
                except ValueError:
                    errors.append(f"Invalid {label}: {val}")

        return errors
