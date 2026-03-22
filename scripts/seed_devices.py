#!/usr/bin/env python3
"""Seed MonCTL with 100 internet-reachable devices + ping/port_check assignments.
API Key: monctl_u_vt0p050j4atqupwjgzpa4nmbig1mwntt
Usage:
    python seed_devices.py \
        --url https://monctl.example.com \
        --api-key monctl_m_abc123 \
        --collector-group "my-group-name"

    # Preview without creating anything:
    python seed_devices.py --url ... --api-key ... --collector-group ... --dry-run

    # Custom intervals:
    python seed_devices.py --url ... --api-key ... --collector-group ... \
        --ping-interval 60 --port-interval 120

    # Only create devices, skip assignments:
    python seed_devices.py --url ... --api-key ... --collector-group ... --skip-assignments

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
# Device list: 100 internet-reachable targets
# ---------------------------------------------------------------------------
# Each tuple: (name, address, device_type, labels)

DEVICES: list[tuple[str, str, str, dict[str, str]]] = [
    # ── DNS Providers (10) ─────────────────────────────────────────────────
    ("dns-google-primary", "8.8.8.8", "host", {"role": "dns", "category": "dns"}),
    ("dns-google-secondary", "8.8.4.4", "host", {"role": "dns", "category": "dns"}),
    ("dns-cloudflare-primary", "1.1.1.1", "host", {"role": "dns", "category": "dns"}),
    ("dns-cloudflare-secondary", "1.0.0.1", "host", {"role": "dns", "category": "dns"}),
    ("dns-quad9-primary", "9.9.9.9", "host", {"role": "dns", "category": "dns"}),
    ("dns-quad9-secondary", "149.112.112.112", "host", {"role": "dns", "category": "dns"}),
    ("dns-opendns-primary", "208.67.222.222", "host", {"role": "dns", "category": "dns"}),
    ("dns-opendns-secondary", "208.67.220.220", "host", {"role": "dns", "category": "dns"}),
    ("dns-adguard-primary", "94.140.14.14", "host", {"role": "dns", "category": "dns"}),
    ("dns-adguard-secondary", "94.140.15.15", "host", {"role": "dns", "category": "dns"}),

    # ── Cloud Providers (10) ───────────────────────────────────────────────
    ("cloud-aws-console", "aws.amazon.com", "api", {"role": "web", "category": "cloud"}),
    ("cloud-azure-portal", "portal.azure.com", "api", {"role": "web", "category": "cloud"}),
    ("cloud-gcp-console", "console.cloud.google.com", "api", {"role": "web", "category": "cloud"}),
    ("cloud-digitalocean", "cloud.digitalocean.com", "api", {"role": "web", "category": "cloud"}),
    ("cloud-linode", "cloud.linode.com", "api", {"role": "web", "category": "cloud"}),
    ("cloud-vultr", "www.vultr.com", "api", {"role": "web", "category": "cloud"}),
    ("cloud-hetzner", "www.hetzner.com", "api", {"role": "web", "category": "cloud"}),
    ("cloud-ovh", "www.ovhcloud.com", "api", {"role": "web", "category": "cloud"}),
    ("cloud-oracle", "cloud.oracle.com", "api", {"role": "web", "category": "cloud"}),
    ("cloud-ibm", "cloud.ibm.com", "api", {"role": "web", "category": "cloud"}),

    # ── CDN / Edge (5) ─────────────────────────────────────────────────────
    ("cdn-cloudflare", "www.cloudflare.com", "api", {"role": "cdn", "category": "cdn"}),
    ("cdn-fastly", "www.fastly.com", "api", {"role": "cdn", "category": "cdn"}),
    ("cdn-akamai", "www.akamai.com", "api", {"role": "cdn", "category": "cdn"}),
    ("cdn-jsdelivr", "cdn.jsdelivr.net", "api", {"role": "cdn", "category": "cdn"}),
    ("cdn-unpkg", "unpkg.com", "api", {"role": "cdn", "category": "cdn"}),

    # ── Major Websites (20) ────────────────────────────────────────────────
    ("web-google", "www.google.com", "api", {"role": "web", "category": "website"}),
    ("web-youtube", "www.youtube.com", "api", {"role": "web", "category": "website"}),
    ("web-github", "github.com", "api", {"role": "web", "category": "website"}),
    ("web-stackoverflow", "stackoverflow.com", "api", {"role": "web", "category": "website"}),
    ("web-reddit", "www.reddit.com", "api", {"role": "web", "category": "website"}),
    ("web-wikipedia", "www.wikipedia.org", "api", {"role": "web", "category": "website"}),
    ("web-twitter", "x.com", "api", {"role": "web", "category": "website"}),
    ("web-linkedin", "www.linkedin.com", "api", {"role": "web", "category": "website"}),
    ("web-facebook", "www.facebook.com", "api", {"role": "web", "category": "website"}),
    ("web-instagram", "www.instagram.com", "api", {"role": "web", "category": "website"}),
    ("web-netflix", "www.netflix.com", "api", {"role": "web", "category": "website"}),
    ("web-spotify", "www.spotify.com", "api", {"role": "web", "category": "website"}),
    ("web-twitch", "www.twitch.tv", "api", {"role": "web", "category": "website"}),
    ("web-discord", "discord.com", "api", {"role": "web", "category": "website"}),
    ("web-slack", "slack.com", "api", {"role": "web", "category": "website"}),
    ("web-notion", "www.notion.so", "api", {"role": "web", "category": "website"}),
    ("web-figma", "www.figma.com", "api", {"role": "web", "category": "website"}),
    ("web-medium", "medium.com", "api", {"role": "web", "category": "website"}),
    ("web-hackernews", "news.ycombinator.com", "api", {"role": "web", "category": "website"}),
    ("web-duckduckgo", "duckduckgo.com", "api", {"role": "web", "category": "website"}),

    # ── DevOps / Monitoring SaaS (10) ──────────────────────────────────────
    ("devops-datadog", "www.datadoghq.com", "api", {"role": "web", "category": "devops"}),
    ("devops-grafana", "grafana.com", "api", {"role": "web", "category": "devops"}),
    ("devops-pagerduty", "www.pagerduty.com", "api", {"role": "web", "category": "devops"}),
    ("devops-sentry", "sentry.io", "api", {"role": "web", "category": "devops"}),
    ("devops-newrelic", "newrelic.com", "api", {"role": "web", "category": "devops"}),
    ("devops-elastic", "www.elastic.co", "api", {"role": "web", "category": "devops"}),
    ("devops-splunk", "www.splunk.com", "api", {"role": "web", "category": "devops"}),
    ("devops-prometheus", "prometheus.io", "api", {"role": "web", "category": "devops"}),
    ("devops-terraform", "www.terraform.io", "api", {"role": "web", "category": "devops"}),
    ("devops-ansible", "www.ansible.com", "api", {"role": "web", "category": "devops"}),

    # ── Package Registries (8) ─────────────────────────────────────────────
    ("registry-pypi", "pypi.org", "api", {"role": "registry", "category": "devops"}),
    ("registry-npm", "registry.npmjs.org", "api", {"role": "registry", "category": "devops"}),
    ("registry-dockerhub", "hub.docker.com", "api", {"role": "registry", "category": "devops"}),
    ("registry-crates", "crates.io", "api", {"role": "registry", "category": "devops"}),
    ("registry-maven", "search.maven.org", "api", {"role": "registry", "category": "devops"}),
    ("registry-nuget", "www.nuget.org", "api", {"role": "registry", "category": "devops"}),
    ("registry-rubygems", "rubygems.org", "api", {"role": "registry", "category": "devops"}),
    ("registry-packagist", "packagist.org", "api", {"role": "registry", "category": "devops"}),

    # ── Code Hosting / CI (7) ──────────────────────────────────────────────
    ("ci-gitlab", "gitlab.com", "api", {"role": "web", "category": "ci"}),
    ("ci-bitbucket", "bitbucket.org", "api", {"role": "web", "category": "ci"}),
    ("ci-circleci", "circleci.com", "api", {"role": "web", "category": "ci"}),
    ("ci-travisci", "www.travis-ci.com", "api", {"role": "web", "category": "ci"}),
    ("ci-jenkins", "www.jenkins.io", "api", {"role": "web", "category": "ci"}),
    ("ci-github-actions", "actions.github.com", "api", {"role": "web", "category": "ci"}),
    ("ci-codecov", "codecov.io", "api", {"role": "web", "category": "ci"}),

    # ── European Targets (10) ─────────────────────────────────────────────
    ("eu-dr-dk", "www.dr.dk", "api", {"role": "web", "category": "regional-eu"}),
    ("eu-bbc", "www.bbc.co.uk", "api", {"role": "web", "category": "regional-eu"}),
    ("eu-spiegel", "www.spiegel.de", "api", {"role": "web", "category": "regional-eu"}),
    ("eu-lemonde", "www.lemonde.fr", "api", {"role": "web", "category": "regional-eu"}),
    ("eu-elpais", "elpais.com", "api", {"role": "web", "category": "regional-eu"}),
    ("eu-corriere", "www.corriere.it", "api", {"role": "web", "category": "regional-eu"}),
    ("eu-nos-nl", "nos.nl", "api", {"role": "web", "category": "regional-eu"}),
    ("eu-svt-se", "www.svt.se", "api", {"role": "web", "category": "regional-eu"}),
    ("eu-yle-fi", "yle.fi", "api", {"role": "web", "category": "regional-eu"}),
    ("eu-nrk-no", "www.nrk.no", "api", {"role": "web", "category": "regional-eu"}),

    # ── US News / Media (10) ───────────────────────────────────────────────
    ("us-nytimes", "www.nytimes.com", "api", {"role": "web", "category": "regional-us"}),
    ("us-washpost", "www.washingtonpost.com", "api", {"role": "web", "category": "regional-us"}),
    ("us-cnn", "www.cnn.com", "api", {"role": "web", "category": "regional-us"}),
    ("us-bbc-us", "www.bbc.com", "api", {"role": "web", "category": "regional-us"}),
    ("us-reuters", "www.reuters.com", "api", {"role": "web", "category": "regional-us"}),
    ("us-apnews", "apnews.com", "api", {"role": "web", "category": "regional-us"}),
    ("us-npr", "www.npr.org", "api", {"role": "web", "category": "regional-us"}),
    ("us-techcrunch", "techcrunch.com", "api", {"role": "web", "category": "regional-us"}),
    ("us-theverge", "www.theverge.com", "api", {"role": "web", "category": "regional-us"}),
    ("us-arstechnica", "arstechnica.com", "api", {"role": "web", "category": "regional-us"}),

    # ── Public Infrastructure (10) ─────────────────────────────────────────
    ("infra-ntp-pool", "pool.ntp.org", "host", {"role": "infrastructure", "category": "public"}),
    ("infra-root-dns-a", "198.41.0.4", "host", {"role": "infrastructure", "category": "public"}),
    ("infra-root-dns-j", "192.58.128.30", "host", {"role": "infrastructure", "category": "public"}),
    ("infra-letsencrypt", "letsencrypt.org", "api", {"role": "infrastructure", "category": "public"}),
    ("infra-archive-org", "archive.org", "api", {"role": "infrastructure", "category": "public"}),
    ("infra-cloudflare-dns-test", "one.one.one.one", "host", {"role": "infrastructure", "category": "public"}),
    ("infra-ietf", "www.ietf.org", "api", {"role": "infrastructure", "category": "public"}),
    ("infra-icann", "www.icann.org", "api", {"role": "infrastructure", "category": "public"}),
    ("infra-ripe", "www.ripe.net", "api", {"role": "infrastructure", "category": "public"}),
    ("infra-apnic", "www.apnic.net", "api", {"role": "infrastructure", "category": "public"}),
]

assert len(DEVICES) == 100, f"Expected 100 devices, got {len(DEVICES)}"


# ---------------------------------------------------------------------------
# HTTP client (stdlib only)
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
    """Find a collector group by name. Returns group_id or None."""
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
        print(f"  ERROR: Failed to list apps (HTTP {status})")
        return None
    for app in data.get("data", []):
        if app["name"] == app_name:
            app_id = app["id"]
            # Fetch app detail to get versions
            s2, detail = api.get(f"/v1/apps/{app_id}")
            if s2 != 200:
                print(f"  ERROR: Failed to get app detail for {app_name} (HTTP {s2})")
                return None
            versions = detail.get("data", {}).get("versions", [])
            latest = next((v for v in versions if v.get("is_latest")), None)
            if latest:
                return app_id, latest["id"]
            # Fallback: first version in the list (already sorted newest first)
            if versions:
                return app_id, versions[0]["id"]
            print(f"  ERROR: App '{app_name}' has no versions")
            return None
    return None


def get_existing_device_names(api: ApiClient) -> set[str]:
    """Fetch all existing device names for idempotency check."""
    names: set[str] = set()
    offset = 0
    limit = 500
    while True:
        status, data = api.get(f"/v1/devices?limit={limit}&offset={offset}")
        if status != 200:
            print(f"  WARNING: Failed to list devices at offset {offset} (HTTP {status})")
            break
        devices = data.get("data", [])
        for d in devices:
            names.add(d["name"])
        if len(devices) < limit:
            break
        offset += limit
    return names


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed MonCTL with 100 internet-reachable devices",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python seed_devices.py --url https://monctl.lab:8444 --api-key monctl_m_abc123 --collector-group Internet
  python seed_devices.py --url https://monctl.lab:8444 --api-key monctl_m_abc123 --collector-group Internet --dry-run
  python seed_devices.py --url https://monctl.lab:8444 --api-key monctl_m_abc123 --collector-group Internet --no-verify-ssl
        """,
    )
    parser.add_argument("--url", required=True, help="MonCTL Central URL (e.g. https://monctl.lab:8444)")
    parser.add_argument("--api-key", required=True, help="Management API key (monctl_m_...)")
    parser.add_argument("--collector-group", required=True, help="Name of existing collector group to assign devices to")
    parser.add_argument("--ping-interval", type=int, default=60, help="Ping check interval in seconds (default: 60)")
    parser.add_argument("--port-interval", type=int, default=120, help="Port check interval in seconds (default: 120)")
    parser.add_argument("--env", default="seed", help="Value for the 'env' label (default: seed)")
    parser.add_argument("--skip-assignments", action="store_true", help="Only create devices, skip app assignments")
    parser.add_argument("--dry-run", action="store_true", help="Preview what would be created without calling the API")
    parser.add_argument("--no-verify-ssl", action="store_true", help="Skip SSL certificate verification")
    args = parser.parse_args()

    api = ApiClient(args.url, args.api_key, verify_ssl=not args.no_verify_ssl)

    print("MonCTL Device Seeder")
    print("=" * 50)
    print(f"  Central URL:      {args.url}")
    print(f"  Collector Group:  {args.collector_group}")
    print(f"  Ping interval:    {args.ping_interval}s")
    print(f"  Port interval:    {args.port_interval}s")
    print(f"  Env label:        {args.env}")
    print(f"  Dry run:          {args.dry_run}")
    print()

    # 1. Health check
    print("Checking connectivity...")
    status, data = api.get("/v1/health")
    if status != 200:
        print(f"  FATAL: Cannot reach Central (HTTP {status})")
        sys.exit(1)
    print("  Connected OK")
    print()

    # 2. Find collector group (must already exist)
    print(f"Looking up collector group '{args.collector_group}'...")
    group_id = find_collector_group(api, args.collector_group)
    if group_id is None:
        print(f"  FATAL: Collector group '{args.collector_group}' not found.")
        print("  Create it first in the UI or via the API, then re-run this script.")
        sys.exit(1)
    print(f"  Found: {group_id}")
    print()

    # 3. Find ping_check and port_check apps
    if not args.skip_assignments:
        print("Looking up apps...")
        ping_app = find_app(api, "ping_check")
        if ping_app is None:
            print("  FATAL: App 'ping_check' not found or has no versions.")
            print("  Create the app and upload at least one version before running this script.")
            sys.exit(1)
        ping_app_id, ping_version_id = ping_app
        print(f"  ping_check: app_id={ping_app_id}, version_id={ping_version_id}")

        port_app = find_app(api, "port_check")
        if port_app is None:
            print("  FATAL: App 'port_check' not found or has no versions.")
            print("  Create the app and upload at least one version before running this script.")
            sys.exit(1)
        port_app_id, port_version_id = port_app
        print(f"  port_check: app_id={port_app_id}, version_id={port_version_id}")
        print()

    # 4. Get existing devices for idempotency
    print("Fetching existing devices...")
    existing_names = get_existing_device_names(api) if not args.dry_run else set()
    print(f"  Found {len(existing_names)} existing devices")
    print()

    # 5. Seed devices
    stats = {"created": 0, "skipped": 0, "assignments": 0, "errors": 0}
    errors: list[str] = []

    print(f"Seeding {len(DEVICES)} devices...")
    print("-" * 50)
    for i, (name, address, device_type, labels) in enumerate(DEVICES, 1):
        prefix = f"  [{i:3d}/{len(DEVICES)}]"
        full_labels = {**labels, "env": args.env}

        # Skip if exists
        if name in existing_names:
            print(f"{prefix} {name} ({address}) — skipped (exists)")
            stats["skipped"] += 1
            continue

        if args.dry_run:
            assign_text = " + 3 assignments" if not args.skip_assignments else ""
            print(f"{prefix} {name} ({address}) — would create{assign_text}")
            stats["created"] += 1
            if not args.skip_assignments:
                stats["assignments"] += 3
            continue

        # Create device
        s, resp = api.post("/v1/devices", {
            "name": name,
            "address": address,
            "device_type": device_type,
            "collector_group_id": group_id,
            "labels": full_labels,
        })

        if s == 409:
            # Already exists (race condition or name collision)
            print(f"{prefix} {name} ({address}) — skipped (409 conflict)")
            stats["skipped"] += 1
            continue

        if s not in (200, 201):
            detail = resp.get("detail", resp)
            msg = f"{name}: device creation failed (HTTP {s}): {detail}"
            print(f"{prefix} {name} ({address}) — ERROR: HTTP {s}")
            errors.append(msg)
            stats["errors"] += 1
            continue

        device_id = resp.get("data", {}).get("id")
        if not device_id:
            msg = f"{name}: no device_id in response"
            print(f"{prefix} {name} ({address}) — ERROR: no id in response")
            errors.append(msg)
            stats["errors"] += 1
            continue

        stats["created"] += 1

        if args.skip_assignments:
            print(f"{prefix} {name} ({address}) ✓")
            continue

        # Create assignments (group-level: no collector_id)
        assignment_defs = [
            ("ping", ping_app_id, ping_version_id, {"count": 3, "timeout": 2}, str(args.ping_interval), "availability"),
            ("port:80", port_app_id, port_version_id, {"port": 80, "timeout": 5}, str(args.port_interval), None),
            ("port:443", port_app_id, port_version_id, {"port": 443, "timeout": 5}, str(args.port_interval), None),
        ]

        assign_ok = 0
        for label, app_id, version_id, config, interval, role in assignment_defs:
            payload: dict[str, Any] = {
                "app_id": app_id,
                "app_version_id": version_id,
                "device_id": device_id,
                "config": config,
                "schedule_type": "interval",
                "schedule_value": interval,
            }
            if role:
                payload["role"] = role

            sa, sr = api.post("/v1/apps/assignments", payload)
            if sa in (200, 201):
                assign_ok += 1
                stats["assignments"] += 1
            else:
                detail = sr.get("detail", sr)
                msg = f"{name}/{label}: assignment failed (HTTP {sa}): {detail}"
                errors.append(msg)
                stats["errors"] += 1

        print(f"{prefix} {name} ({address}) ✓ + {assign_ok} assignments")

    # 6. Summary
    print()
    print("=" * 50)
    print("Summary")
    print("-" * 50)
    print(f"  Devices created:      {stats['created']}")
    print(f"  Devices skipped:      {stats['skipped']}")
    print(f"  Assignments created:  {stats['assignments']}")
    print(f"  Errors:               {stats['errors']}")

    if errors:
        print()
        print("Errors:")
        for e in errors:
            print(f"  • {e}")

    if args.dry_run:
        print()
        print("(dry run — nothing was actually created)")

    sys.exit(1 if stats["errors"] > 0 else 0)


if __name__ == "__main__":
    main()
