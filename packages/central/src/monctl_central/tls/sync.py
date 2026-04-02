"""TLS certificate sync — keeps local HAProxy cert in sync with DB.

Runs on EVERY central instance (not leader-gated). Periodically checks
if the active certificate in PostgreSQL differs from the on-disk PEM
and writes the updated cert + reloads HAProxy when needed.
"""

from __future__ import annotations

import asyncio
import http.client
import socket
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.config import settings
from monctl_central.credentials.crypto import decrypt_dict
from monctl_central.storage.models import TlsCertificate

logger = structlog.get_logger()

_SYNC_INTERVAL = 60  # seconds


async def sync_cert_to_disk(session_factory) -> bool:
    """Check DB for active cert and write to disk if changed.

    Returns True if a new cert was written.
    """
    cert_path = Path(settings.tls_cert_path)
    marker_path = cert_path.parent / ".cert-id"

    async with session_factory() as session:
        stmt = select(TlsCertificate).where(TlsCertificate.is_active == True)  # noqa: E712
        cert = (await session.execute(stmt)).scalar_one_or_none()

    if cert is None:
        return False

    cert_id = str(cert.id)

    # Check marker to see if we already have this cert on disk
    if marker_path.exists():
        try:
            on_disk_id = marker_path.read_text().strip()
            if on_disk_id == cert_id:
                return False  # Already up to date
        except Exception:
            pass

    # Decrypt private key and write combined PEM
    try:
        key_data = decrypt_dict(cert.key_pem_encrypted)
        key_pem = key_data.get("key", "")
    except Exception:
        logger.error("tls_sync_decrypt_failed", cert_id=cert_id)
        return False

    try:
        cert_path.parent.mkdir(parents=True, exist_ok=True)
        cert_path.write_text(cert.cert_pem + key_pem)
        cert_path.chmod(0o600)
        marker_path.write_text(cert_id)
        logger.info("tls_cert_written", cert_id=cert_id, path=str(cert_path))
    except Exception:
        logger.error("tls_sync_write_failed", cert_id=cert_id, exc_info=True)
        return False

    # Reload HAProxy via Docker (central and HAProxy share the named volume)
    _reload_haproxy()
    return True


def _reload_haproxy() -> None:
    """Send SIGHUP to the haproxy container via Docker socket API."""
    docker_sock = Path("/var/run/docker.sock")
    if not docker_sock.exists():
        logger.debug("tls_sync_docker_socket_not_found")
        return

    try:
        # Use Unix socket HTTP to call Docker Engine API
        conn = http.client.HTTPConnection("localhost")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(docker_sock))
        conn.sock = sock
        conn.request("POST", "/containers/haproxy/kill?signal=HUP")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        if resp.status == 204:
            logger.info("haproxy_reloaded")
        else:
            logger.warning("haproxy_reload_unexpected_status", status=resp.status)
    except Exception as exc:
        logger.warning("haproxy_reload_failed", error=str(exc))


async def run_cert_sync_loop(session_factory) -> None:
    """Background loop that syncs cert from DB to disk every 60s.

    Runs on all central instances (not gated by leader election).
    """
    # Immediate sync on startup
    try:
        await sync_cert_to_disk(session_factory)
    except Exception:
        logger.warning("tls_sync_initial_failed", exc_info=True)

    while True:
        await asyncio.sleep(_SYNC_INTERVAL)
        try:
            await sync_cert_to_disk(session_factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("tls_sync_error", exc_info=True)
