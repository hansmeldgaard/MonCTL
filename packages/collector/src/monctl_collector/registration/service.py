"""Collector registration with central server."""

from __future__ import annotations

import json
import os
import platform
import socket

import httpx
import structlog

from monctl_collector.config import collector_settings

logger = structlog.get_logger()


async def register_collector(
    central_url: str,
    registration_token: str,
    cluster_id: str | None = None,
    peer_address: str | None = None,
    labels: dict[str, str] | None = None,
) -> dict:
    """Register this collector with the central server.

    Stores the received API key and collector ID locally.
    """
    hostname = socket.gethostname()
    os_info = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
    }

    # Get local IP addresses
    ip_addresses = []
    try:
        for addr_info in socket.getaddrinfo(hostname, None):
            addr = addr_info[4][0]
            if addr not in ip_addresses and not addr.startswith("127."):
                ip_addresses.append(addr)
    except socket.gaierror:
        pass

    payload = {
        "hostname": hostname,
        "registration_token": registration_token,
        "os_info": os_info,
        "ip_addresses": ip_addresses,
        "labels": labels or {},
        "cluster_id": cluster_id,
        "peer_address": peer_address or f"{hostname}:{collector_settings.peer_port}",
    }

    async with httpx.AsyncClient(verify=collector_settings.verify_ssl) as client:
        response = await client.post(
            f"{central_url}/v1/collectors/register",
            json=payload,
            timeout=30,
        )

        if response.status_code != 201:
            logger.error("registration_failed", status=response.status_code, body=response.text)
            raise RuntimeError(f"Registration failed: {response.status_code} {response.text}")

        data = response.json()

    collector_id = data["collector_id"]
    api_key = data["api_key"]
    name = data["name"]

    # Store credentials locally
    credentials = {
        "collector_id": collector_id,
        "api_key": api_key,
        "central_url": central_url,
        "name": name,
    }

    creds_dir = os.path.dirname(collector_settings.credentials_file)
    os.makedirs(creds_dir, exist_ok=True)

    with open(collector_settings.credentials_file, "w") as f:
        json.dump(credentials, f, indent=2)
    os.chmod(collector_settings.credentials_file, 0o600)

    logger.info("registration_successful", collector_id=collector_id, name=name)
    return credentials
