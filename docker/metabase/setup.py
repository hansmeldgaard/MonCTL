#!/usr/bin/env python3
"""One-time Metabase setup: admin user, ClickHouse datasource, seed dashboards.

Usage:
    python setup.py --metabase-url http://localhost:3000 \
                    --admin-email admin@monctl.local \
                    --admin-password <password> \
                    --clickhouse-host 10.145.210.43 \
                    --clickhouse-port 8123 \
                    --clickhouse-db monctl \
                    --seed-dir ./seed-dashboards
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests


def wait_for_metabase(base_url: str, timeout: int = 120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"{base_url}/api/health", timeout=5)
            if resp.status_code == 200 and resp.json().get("status") == "ok":
                print("Metabase is ready.")
                return
        except Exception:
            pass
        time.sleep(3)
    print("ERROR: Metabase did not become ready in time.", file=sys.stderr)
    sys.exit(1)


def get_setup_token(base_url: str) -> str:
    resp = requests.get(f"{base_url}/api/session/properties")
    resp.raise_for_status()
    token = resp.json().get("setup-token")
    if not token:
        print("Setup token not found — Metabase may already be configured.")
        return ""
    return token


def initial_setup(base_url: str, admin_email: str, admin_password: str, setup_token: str):
    payload = {
        "token": setup_token,
        "user": {
            "email": admin_email,
            "first_name": "MonCTL",
            "last_name": "Admin",
            "password": admin_password,
            "site_name": "MonCTL Analytics",
        },
        "prefs": {
            "site_name": "MonCTL Analytics",
            "site_locale": "en",
            "allow_tracking": False,
        },
    }
    resp = requests.post(f"{base_url}/api/setup", json=payload)
    resp.raise_for_status()
    print("Initial setup complete.")
    return resp.json().get("id")


def login(base_url: str, email: str, password: str) -> str:
    resp = requests.post(f"{base_url}/api/session", json={
        "username": email,
        "password": password,
    })
    resp.raise_for_status()
    return resp.json()["id"]


def add_clickhouse_datasource(base_url: str, session: str,
                               ch_host: str, ch_port: int, ch_db: str,
                               ch_user: str = "monctl", ch_password: str = "monctl"):
    headers = {"X-Metabase-Session": session}

    resp = requests.get(f"{base_url}/api/database", headers=headers)
    resp.raise_for_status()
    for db in resp.json().get("data", []):
        if db.get("engine") == "clickhouse":
            print(f"ClickHouse datasource already exists (id={db['id']}).")
            return db["id"]

    payload = {
        "engine": "clickhouse",
        "name": "MonCTL ClickHouse",
        "details": {
            "host": ch_host,
            "port": ch_port,
            "dbname": ch_db,
            "user": ch_user,
            "password": ch_password,
            "ssl": False,
        },
        "is_on_demand": False,
        "is_full_sync": True,
        "auto_run_queries": True,
    }
    resp = requests.post(f"{base_url}/api/database", json=payload, headers=headers)
    resp.raise_for_status()
    db_id = resp.json()["id"]
    print(f"ClickHouse datasource added (id={db_id}).")

    requests.post(f"{base_url}/api/database/{db_id}/sync_schema", headers=headers)
    print("Schema sync triggered.")
    return db_id


def create_collection(base_url: str, session: str, name: str) -> int:
    headers = {"X-Metabase-Session": session}

    resp = requests.get(f"{base_url}/api/collection", headers=headers)
    resp.raise_for_status()
    for col in resp.json():
        if col.get("name") == name and col.get("archived") is False:
            print(f"Collection '{name}' already exists (id={col['id']}).")
            return col["id"]

    resp = requests.post(f"{base_url}/api/collection", json={
        "name": name,
        "description": "Pre-built MonCTL dashboards and questions",
    }, headers=headers)
    resp.raise_for_status()
    col_id = resp.json()["id"]
    print(f"Collection '{name}' created (id={col_id}).")
    return col_id


def seed_dashboards(base_url: str, session: str, db_id: int,
                     collection_id: int, seed_dir: str):
    headers = {"X-Metabase-Session": session}
    seed_path = Path(seed_dir)

    if not seed_path.exists():
        print(f"Seed directory {seed_dir} not found, skipping.")
        return

    for json_file in sorted(seed_path.glob("*.json")):
        print(f"Seeding: {json_file.name}")
        with open(json_file) as f:
            seed_data = json.load(f)

        card_id_map: dict[str, int] = {}
        for question in seed_data.get("questions", []):
            question["database_id"] = db_id
            question["collection_id"] = collection_id
            resp = requests.post(f"{base_url}/api/card", json=question, headers=headers)
            if resp.status_code == 200:
                card_id = resp.json()["id"]
                local_ref = question.get("_ref", question["name"])
                card_id_map[local_ref] = card_id
                print(f"  Created question: {question['name']} (id={card_id})")
            else:
                print(f"  WARN: Failed to create question {question['name']}: {resp.text}")

        dashboard_def = seed_data.get("dashboard")
        if dashboard_def:
            dashboard_def["collection_id"] = collection_id
            resp = requests.post(f"{base_url}/api/dashboard", json={
                "name": dashboard_def["name"],
                "description": dashboard_def.get("description", ""),
                "collection_id": collection_id,
            }, headers=headers)
            if resp.status_code == 200:
                dash_id = resp.json()["id"]
                print(f"  Created dashboard: {dashboard_def['name']} (id={dash_id})")

                for card_layout in dashboard_def.get("cards", []):
                    ref = card_layout.pop("_ref", None)
                    if ref and ref in card_id_map:
                        card_layout["card_id"] = card_id_map[ref]
                    resp = requests.post(
                        f"{base_url}/api/dashboard/{dash_id}/cards",
                        json=card_layout,
                        headers=headers,
                    )
                    if resp.status_code != 200:
                        print(f"  WARN: Failed to add card to dashboard: {resp.text}")
            else:
                print(f"  WARN: Failed to create dashboard: {resp.text}")


def main():
    parser = argparse.ArgumentParser(description="Metabase one-time setup for MonCTL")
    parser.add_argument("--metabase-url", default="http://localhost:3000")
    parser.add_argument("--admin-email", default="admin@monctl.local")
    parser.add_argument("--admin-password", required=True)
    parser.add_argument("--clickhouse-host", default="10.145.210.43")
    parser.add_argument("--clickhouse-port", type=int, default=8123)
    parser.add_argument("--clickhouse-db", default="monctl")
    parser.add_argument("--clickhouse-user", default="monctl")
    parser.add_argument("--clickhouse-password", default="monctl")
    parser.add_argument("--seed-dir", default="./seed-dashboards")
    args = parser.parse_args()

    wait_for_metabase(args.metabase_url)

    setup_token = get_setup_token(args.metabase_url)
    if setup_token:
        initial_setup(args.metabase_url, args.admin_email, args.admin_password, setup_token)

    session = login(args.metabase_url, args.admin_email, args.admin_password)
    db_id = add_clickhouse_datasource(
        args.metabase_url, session,
        args.clickhouse_host, args.clickhouse_port, args.clickhouse_db,
        args.clickhouse_user, args.clickhouse_password,
    )
    col_id = create_collection(args.metabase_url, session, "MonCTL")
    seed_dashboards(args.metabase_url, session, db_id, col_id, args.seed_dir)

    print("\nSetup complete!")
    print(f"  Metabase: {args.metabase_url}")
    print(f"  Admin: {args.admin_email}")


if __name__ == "__main__":
    main()
