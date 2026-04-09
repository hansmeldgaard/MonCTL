#!/usr/bin/env python3
"""Seed MonCTL with simulated devices pointing to the device simulator.

Creates devices, credentials, and app assignments that poll the simulator's
SNMP/HTTP/TCP endpoints.

Usage:
    python scripts/seed_simulator.py \
        --url https://10.145.210.40 \
        --api-key monctl_m_abc123 \
        --collector-group "my-group"

    # Custom simulator host and device count:
    python scripts/seed_simulator.py \
        --url https://10.145.210.40 \
        --api-key monctl_m_abc123 \
        --collector-group "my-group" \
        --simulator-host 10.145.210.10 \
        --device-count 50

    # Preview without creating anything:
    python scripts/seed_simulator.py ... --dry-run

Requirements: Python 3.9+ (stdlib only, no pip install needed)
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from typing import Any

# ---------------------------------------------------------------------------
# Device simulator profiles (must match simulator/config.yaml)
# ---------------------------------------------------------------------------

DEVICE_GROUPS = [
    {"count": 40, "type": "cisco-switch",   "interfaces": 24, "category": "network"},
    {"count": 20, "type": "cisco-router",   "interfaces": 8,  "category": "network"},
    {"count": 20, "type": "juniper-switch", "interfaces": 48, "category": "network"},
    {"count": 10, "type": "juniper-router", "interfaces": 12, "category": "network"},
    {"count": 10, "type": "linux-host",     "interfaces": 4,  "category": "host",
     "http": True, "tcp_ports": [22, 80, 443]},
]


# ---------------------------------------------------------------------------
# HTTP client (stdlib only — same pattern as seed_devices.py)
# ---------------------------------------------------------------------------

class ApiClient:
    def __init__(self, base_url: str, api_key: str, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.ctx: ssl.SSLContext | None = None
        if not verify_ssl:
            self.ctx = ssl.create_default_context()
            self.ctx.check_hostname = False
            self.ctx.verify_mode = ssl.CERT_NONE

    def _request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        try:
            resp = urllib.request.urlopen(req, context=self.ctx, timeout=30)
            resp_body = resp.read().decode()
            return resp.status, json.loads(resp_body) if resp_body else {}
        except urllib.error.HTTPError as e:
            resp_body = e.read().decode()
            try:
                return e.code, json.loads(resp_body)
            except json.JSONDecodeError:
                return e.code, {"detail": resp_body}

    def get(self, path: str) -> tuple[int, dict]:
        return self._request("GET", path)

    def post(self, path: str, body: dict) -> tuple[int, dict]:
        return self._request("POST", path, body)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def find_collector_group(api: ApiClient, name: str) -> str | None:
    status, data = api.get("/v1/collector-groups")
    if status != 200:
        print(f"  ERROR: Failed to list collector groups (HTTP {status})")
        return None
    for g in data.get("data", []):
        if g["name"] == name:
            return g["id"]
    return None


def find_app(api: ApiClient, app_name: str) -> tuple[str, str] | None:
    """Find an app by name, return (app_id, latest_version_id) or None."""
    status, data = api.get("/v1/apps")
    if status != 200:
        return None
    for app in data.get("data", []):
        if app["name"] == app_name:
            app_id = app["id"]
            s2, detail = api.get(f"/v1/apps/{app_id}")
            if s2 != 200:
                return None
            versions = detail.get("data", {}).get("versions", [])
            latest = next((v for v in versions if v.get("is_latest")), None)
            if latest:
                return app_id, latest["id"]
            if versions:
                return app_id, versions[0]["id"]
            return None
    return None


def find_connector(api: ApiClient, name: str) -> tuple[str, str] | None:
    """Find a connector by name, return (connector_id, latest_version_id) or None."""
    status, data = api.get("/v1/connectors")
    if status != 200:
        return None
    for conn in data.get("data", []):
        if conn["name"] == name:
            conn_id = conn["id"]
            s2, detail = api.get(f"/v1/connectors/{conn_id}")
            if s2 != 200:
                return None
            versions = detail.get("data", {}).get("versions", [])
            if versions:
                return conn_id, versions[0]["id"]
            return None
    return None


def find_credential(api: ApiClient, name: str) -> str | None:
    """Find a credential by name, return credential_id or None."""
    status, data = api.get("/v1/credentials")
    if status != 200:
        return None
    for cred in data.get("data", []):
        if cred["name"] == name:
            return cred["id"]
    return None


def get_existing_device_names(api: ApiClient) -> set[str]:
    names: set[str] = set()
    offset = 0
    while True:
        status, data = api.get(f"/v1/devices?limit=500&offset={offset}")
        if status != 200:
            break
        devices = data.get("data", [])
        for d in devices:
            names.add(d["name"])
        if len(devices) < 500:
            break
        offset += 500
    return names


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed MonCTL with simulated devices for stress testing",
    )
    parser.add_argument("--url", required=True, help="MonCTL Central URL")
    parser.add_argument("--api-key", required=True, help="Management API key")
    parser.add_argument("--collector-group", required=True, help="Collector group name")
    parser.add_argument("--simulator-host", default="10.145.210.10",
                        help="IP of the simulator host (default: 10.145.210.10)")
    parser.add_argument("--snmp-port-start", type=int, default=11000,
                        help="First SNMP port (default: 11000)")
    parser.add_argument("--http-port-start", type=int, default=12000,
                        help="First HTTP port (default: 12000)")
    parser.add_argument("--tcp-port-start", type=int, default=13000,
                        help="First TCP port (default: 13000)")
    parser.add_argument("--device-count", type=int, default=None,
                        help="Override total device count (scales proportionally)")
    parser.add_argument("--name-prefix", default="sim",
                        help="Device name prefix (default: sim). E.g. 'test' → test_001")
    parser.add_argument("--snmp-interval", type=int, default=60,
                        help="SNMP poll interval in seconds (default: 60)")
    parser.add_argument("--ping-interval", type=int, default=60,
                        help="Ping check interval in seconds (default: 60)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-verify-ssl", action="store_true")
    parser.add_argument("--skip-assignments", action="store_true",
                        help="Only create devices, skip app assignments")
    args = parser.parse_args()

    api = ApiClient(args.url, args.api_key, verify_ssl=not args.no_verify_ssl)

    print("MonCTL Simulator Seeder")
    print("=" * 60)
    print(f"  Central URL:       {args.url}")
    print(f"  Simulator host:    {args.simulator_host}")
    print(f"  Collector Group:   {args.collector_group}")
    print(f"  SNMP port start:   {args.snmp_port_start}")
    print(f"  Dry run:           {args.dry_run}")
    print()

    # 1. Health check
    print("Checking connectivity...")
    status, _ = api.get("/v1/health")
    if status != 200:
        print(f"  FATAL: Cannot reach Central (HTTP {status})")
        sys.exit(1)
    print("  Connected OK\n")

    # 2. Find collector group
    print(f"Looking up collector group '{args.collector_group}'...")
    group_id = find_collector_group(api, args.collector_group)
    if group_id is None:
        print(f"  FATAL: Collector group '{args.collector_group}' not found.")
        sys.exit(1)
    print(f"  Found: {group_id}\n")

    # 3. Find apps and connector
    apps_needed = {}
    if not args.skip_assignments:
        print("Looking up apps and connectors...")
        for app_name in ["ping_check", "snmp_check", "snmp_interface_poller", "http_check", "port_check"]:
            result = find_app(api, app_name)
            if result:
                apps_needed[app_name] = result
                print(f"  {app_name}: OK")
            else:
                print(f"  {app_name}: not found (will skip assignments for this app)")

        snmp_conn = find_connector(api, "snmp")
        if snmp_conn:
            print(f"  snmp connector: OK")
        else:
            print("  WARNING: SNMP connector not found — SNMP assignments will be skipped")
        print()

    # 4. Find or create simulator credential
    cred_name = "sim-snmp-public"
    cred_id = None
    if not args.dry_run and not args.skip_assignments:
        print(f"Looking up credential '{cred_name}'...")
        cred_id = find_credential(api, cred_name)
        if cred_id:
            print(f"  Found existing: {cred_id}")
        else:
            print("  Not found, creating...")
            s, resp = api.post("/v1/credentials", {
                "name": cred_name,
                "credential_type": "snmpv2c",
                "description": "Simulator SNMPv2c community (public)",
                "values": {"community": "public", "version": "2c"},
            })
            if s in (200, 201):
                cred_id = resp.get("data", {}).get("id")
                print(f"  Created: {cred_id}")
            else:
                print(f"  WARNING: Failed to create credential (HTTP {s}): {resp}")
        print()

    # 5. Get existing devices
    print("Fetching existing devices...")
    existing_names = get_existing_device_names(api) if not args.dry_run else set()
    print(f"  Found {len(existing_names)} existing devices\n")

    # 6. Build device list from profiles
    devices_to_create = []
    snmp_port = args.snmp_port_start
    http_port = args.http_port_start
    tcp_port = args.tcp_port_start

    for group in DEVICE_GROUPS:
        count = group["count"]
        if args.device_count:
            # Scale proportionally
            total_default = sum(g["count"] for g in DEVICE_GROUPS)
            count = max(1, round(args.device_count * group["count"] / total_default))

        for i in range(count):
            seq = len(devices_to_create) + 1
            dtype = group["type"]
            prefix = args.name_prefix if hasattr(args, 'name_prefix') else "sim"
            name = f"{prefix}_{seq:03d}" if prefix != "sim" else f"sim-{dtype}-{seq:03d}"

            device_info = {
                "name": name,
                "address": args.simulator_host,
                "category": group["category"],
                "type": dtype,
                "snmp_port": snmp_port,
                "http_port": http_port if group.get("http") else None,
                "tcp_ports": [],
            }
            if group.get("tcp_ports"):
                device_info["tcp_ports"] = [tcp_port + j for j in range(len(group["tcp_ports"]))]
                tcp_port += len(group["tcp_ports"])
            if group.get("http"):
                http_port += 1

            devices_to_create.append(device_info)
            snmp_port += 1

    # 7. Create devices and assignments
    stats = {"created": 0, "skipped": 0, "assignments": 0, "errors": 0}
    errors: list[str] = []

    print(f"Seeding {len(devices_to_create)} simulated devices...")
    print("-" * 60)

    for i, dev in enumerate(devices_to_create, 1):
        prefix = f"  [{i:3d}/{len(devices_to_create)}]"
        name = dev["name"]

        if name in existing_names:
            print(f"{prefix} {name} — skipped (exists)")
            stats["skipped"] += 1
            continue

        if args.dry_run:
            print(f"{prefix} {name} (:{dev['snmp_port']}) — would create")
            stats["created"] += 1
            continue

        # Create device
        labels = {
            "env": "simulator",
            "sim_type": dev["type"],
            "sim_snmp_port": str(dev["snmp_port"]),
        }
        s, resp = api.post("/v1/devices", {
            "name": name,
            "address": dev["address"],
            "device_category": dev["category"],
            "collector_group_id": group_id,
            "labels": labels,
        })

        if s == 409:
            print(f"{prefix} {name} — skipped (409)")
            stats["skipped"] += 1
            continue
        if s not in (200, 201):
            msg = f"{name}: device creation failed (HTTP {s})"
            print(f"{prefix} {name} — ERROR: HTTP {s}")
            errors.append(msg)
            stats["errors"] += 1
            continue

        device_id = resp.get("data", {}).get("id")
        if not device_id:
            print(f"{prefix} {name} — ERROR: no id")
            stats["errors"] += 1
            continue

        stats["created"] += 1

        if args.skip_assignments:
            print(f"{prefix} {name} (:{dev['snmp_port']})")
            continue

        # Set default credential on device
        if cred_id:
            api._request("PATCH", f"/v1/devices/{device_id}", {
                "default_credential_id": cred_id,
            })

        assign_ok = 0

        # Ping check
        if "ping_check" in apps_needed:
            app_id, ver_id = apps_needed["ping_check"]
            s, _ = api.post("/v1/apps/assignments", {
                "app_id": app_id,
                "app_version_id": ver_id,
                "device_id": device_id,
                "config": {"count": 3, "timeout": 2},
                "schedule_type": "interval",
                "schedule_value": str(args.ping_interval),
                "role": "availability",
            })
            if s in (200, 201):
                assign_ok += 1
                stats["assignments"] += 1

        # SNMP check (with connector binding for custom port)
        if "snmp_check" in apps_needed and snmp_conn:
            app_id, ver_id = apps_needed["snmp_check"]
            conn_id, conn_ver_id = snmp_conn
            s, _ = api.post("/v1/apps/assignments", {
                "app_id": app_id,
                "app_version_id": ver_id,
                "device_id": device_id,
                "config": {"oid": "1.3.6.1.2.1.1.3.0"},
                "schedule_type": "interval",
                "schedule_value": str(args.snmp_interval),
                "connector_bindings": [{
                    "alias": "snmp",
                    "connector_id": conn_id,
                    "connector_version_id": conn_ver_id,
                    "credential_id": cred_id,
                    "settings": {"port": dev["snmp_port"]},
                }],
            })
            if s in (200, 201):
                assign_ok += 1
                stats["assignments"] += 1
            else:
                errors.append(f"{name}/snmp_check: HTTP {s}")

        # SNMP interface poller (network devices only)
        if "snmp_interface_poller" in apps_needed and snmp_conn and dev["category"] == "network":
            app_id, ver_id = apps_needed["snmp_interface_poller"]
            conn_id, conn_ver_id = snmp_conn
            s, _ = api.post("/v1/apps/assignments", {
                "app_id": app_id,
                "app_version_id": ver_id,
                "device_id": device_id,
                "config": {},
                "schedule_type": "interval",
                "schedule_value": str(args.snmp_interval),
                "connector_bindings": [{
                    "alias": "snmp",
                    "connector_id": conn_id,
                    "connector_version_id": conn_ver_id,
                    "credential_id": cred_id,
                    "settings": {"port": dev["snmp_port"]},
                }],
            })
            if s in (200, 201):
                assign_ok += 1
                stats["assignments"] += 1
            else:
                errors.append(f"{name}/snmp_interface_poller: HTTP {s}")

        # HTTP check (devices with http_port)
        if "http_check" in apps_needed and dev["http_port"]:
            app_id, ver_id = apps_needed["http_check"]
            s, _ = api.post("/v1/apps/assignments", {
                "app_id": app_id,
                "app_version_id": ver_id,
                "device_id": device_id,
                "config": {
                    "url": f"http://{dev['address']}:{dev['http_port']}/",
                    "timeout": 10,
                    "verify_ssl": False,
                },
                "schedule_type": "interval",
                "schedule_value": str(args.ping_interval),
            })
            if s in (200, 201):
                assign_ok += 1
                stats["assignments"] += 1

        # Port checks
        if "port_check" in apps_needed and dev["tcp_ports"]:
            app_id, ver_id = apps_needed["port_check"]
            for tcp_p in dev["tcp_ports"]:
                s, _ = api.post("/v1/apps/assignments", {
                    "app_id": app_id,
                    "app_version_id": ver_id,
                    "device_id": device_id,
                    "config": {"port": tcp_p, "timeout": 5},
                    "schedule_type": "interval",
                    "schedule_value": str(args.ping_interval),
                })
                if s in (200, 201):
                    assign_ok += 1
                    stats["assignments"] += 1

        print(f"{prefix} {name} (:{dev['snmp_port']}) + {assign_ok} assignments")

    # 8. Summary
    print()
    print("=" * 60)
    print("Summary")
    print("-" * 60)
    print(f"  Devices created:      {stats['created']}")
    print(f"  Devices skipped:      {stats['skipped']}")
    print(f"  Assignments created:  {stats['assignments']}")
    print(f"  Errors:               {stats['errors']}")

    if errors:
        print()
        print("Errors:")
        for e in errors[:20]:
            print(f"  - {e}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")

    if args.dry_run:
        print("\n(dry run — nothing was actually created)")

    sys.exit(1 if stats["errors"] > 0 else 0)


if __name__ == "__main__":
    main()
