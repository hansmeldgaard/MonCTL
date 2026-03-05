"""MonCTL Central Server - FastAPI application."""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from monctl_central.config import settings
from monctl_central.dependencies import get_engine, get_session_factory

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    # Generate instance ID if not set
    if not settings.instance_id:
        settings.instance_id = str(uuid.uuid4())[:8]

    logger.info(
        "central_starting",
        instance_id=settings.instance_id,
        host=settings.host,
        port=settings.port,
    )

    from sqlalchemy import select
    from monctl_central.storage.models import App, AppVersion, DeviceType, User

    factory = get_session_factory()

    # Seed admin user if MONCTL_ADMIN_PASSWORD is set and no users exist
    if settings.admin_password:
        from monctl_central.auth.service import hash_password

        async with factory() as session:
            existing = (await session.execute(select(User).limit(1))).scalar_one_or_none()
            if existing is None:
                admin = User(
                    username=settings.admin_username,
                    password_hash=hash_password(settings.admin_password),
                    role="admin",
                    display_name="Administrator",
                )
                session.add(admin)
                await session.commit()
                logger.info("admin_user_created", username=settings.admin_username)

    # Seed default device types if none exist
    _DEFAULT_DEVICE_TYPES = [
        ("host", "Generic server, VM, or physical machine"),
        ("network", "Network device — router, switch, firewall, access point"),
        ("api", "HTTP API endpoint or web service"),
        ("database", "Database server — PostgreSQL, MySQL, Redis, etc."),
        ("service", "Application service or microservice"),
        ("container", "Docker container or Kubernetes pod"),
        ("virtual-machine", "Hypervisor-managed virtual machine"),
        ("storage", "Storage array, NAS, or SAN device"),
        ("printer", "Printer or print server"),
        ("iot", "IoT or embedded device"),
    ]
    async with factory() as session:
        count = (await session.execute(select(DeviceType).limit(1))).scalar_one_or_none()
        if count is None:
            for name, description in _DEFAULT_DEVICE_TYPES:
                session.add(DeviceType(name=name, description=description))
            await session.commit()
            logger.info("device_types_seeded", count=len(_DEFAULT_DEVICE_TYPES))

    # Seed built-in monitoring apps (ping_check, port_check, snmp_check)
    _BUILTIN_APPS = [
        ("ping_check", "Built-in ICMP ping check"),
        ("port_check", "Built-in TCP port check"),
        ("snmp_check", "Built-in SNMP check (v1/v2c/v3)"),
    ]
    async with factory() as session:
        for app_name, desc in _BUILTIN_APPS:
            existing_app = (
                await session.execute(select(App).where(App.name == app_name))
            ).scalar_one_or_none()
            if existing_app is None:
                app_obj = App(name=app_name, description=desc, app_type="builtin")
                session.add(app_obj)
                await session.flush()
                session.add(AppVersion(
                    app_id=app_obj.id,
                    version="1.0.0",
                    checksum_sha256="0" * 64,
                    archive_path=None,
                ))
        await session.commit()
        logger.info("builtin_apps_seeded")

    # ── Collector health monitor ──────────────────────────────────────────────
    # Runs every 60 s; marks collectors that haven't sent a heartbeat in 90 s as
    # DOWN and bumps the config_version of their surviving group siblings so those
    # collectors re-fetch config and pick up the redistributed assignments.

    async def _health_monitor():
        STALE_SECONDS = 90  # 3× the 30-second heartbeat interval
        while True:
            await asyncio.sleep(60)
            try:
                from sqlalchemy import select, update
                from monctl_central.storage.models import Collector
                from monctl_common.utils import utc_now

                cutoff = utc_now() - timedelta(seconds=STALE_SECONDS)
                _factory = get_session_factory()
                async with _factory() as session:
                    stale = (
                        await session.execute(
                            select(Collector).where(
                                Collector.status == "ACTIVE",
                                Collector.last_seen_at < cutoff,
                            )
                        )
                    ).scalars().all()

                    for c in stale:
                        c.status = "DOWN"
                        c.updated_at = utc_now()
                        logger.info(
                            "collector_marked_down",
                            collector_id=str(c.id),
                            name=c.name,
                            last_seen_at=str(c.last_seen_at),
                        )
                        # Bump surviving group members so they re-fetch config
                        # and pick up the work that was on the dead collector.
                        if c.group_id:
                            await session.execute(
                                update(Collector)
                                .where(
                                    Collector.group_id == c.group_id,
                                    Collector.id != c.id,
                                    Collector.status == "ACTIVE",
                                )
                                .values(
                                    config_version=Collector.config_version + 1,
                                    updated_at=utc_now(),
                                )
                            )

                    if stale:
                        await session.commit()
                        logger.info(
                            "collector_health_check",
                            marked_down=len(stale),
                        )

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("collector_health_monitor_error")

    health_task = asyncio.create_task(_health_monitor())

    yield

    # Shutdown
    health_task.cancel()
    try:
        await health_task
    except asyncio.CancelledError:
        pass

    engine = get_engine()
    await engine.dispose()
    logger.info("central_stopped", instance_id=settings.instance_id)


_DESCRIPTION = """
MonCTL is a distributed monitoring platform. Collectors run monitoring apps and push
results to this central server, which stores them and exposes query and management APIs.

## Authentication

**Web UI**: Login at `/` with username and password.

**API**: All endpoints except `/v1/health` require a Bearer token in the `Authorization` header:

```
Authorization: Bearer monctl_m_<key>   \u2190 management operations
Authorization: Bearer monctl_c_<key>   \u2190 collector communication
```

Management keys are created via the database seed script or the admin CLI.
Collector keys are issued automatically during collector registration.

## Quick start

1. **Register devices** \u2014 `POST /v1/devices`
2. **Create credentials** (if needed) \u2014 `POST /v1/credentials`
3. **Assign an app to a collector** \u2014 `POST /v1/apps/assignments` (link `device_id` for auto host injection)
4. **Query results** \u2014 `GET /v1/results/by-device/{device_id}` for per-device status

## Credential references in app config

Use `"$credential:name"` in any assignment config value. Central resolves it to the
decrypted secret before sending config to the collector:

```json
{"host": "192.168.1.1", "community": "$credential:snmp-prod"}
```
"""

_TAGS = [
    {"name": "system",      "description": "Health check and system status. No auth required for `/v1/health`."},
    {"name": "auth",        "description": "User authentication for the web UI (login, logout, token refresh)."},
    {"name": "collectors",  "description": "Collector registration, heartbeat, and config snapshot delivery."},
    {"name": "ingestion",   "description": "Data ingestion endpoint used by collectors to push check results and events."},
    {"name": "devices",     "description": "Device inventory \u2014 the things you want to monitor (servers, routers, APIs, etc.)."},
    {"name": "apps",        "description": "Monitoring apps, versions, and assignments (which app runs on which collector/device)."},
    {"name": "credentials", "description": "Encrypted credential storage. Secrets are AES-256-GCM encrypted at rest and never returned by the API."},
    {"name": "results",     "description": "Query check results. Use `/v1/results/by-device/{id}` for a per-device status dashboard."},
    {"name": "alerting",    "description": "Alert rules and active alerts."},
]

app = FastAPI(
    title="MonCTL Central",
    description=_DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=_TAGS,
    contact={"name": "MonCTL", "url": "https://github.com/your-org/monctl"},
    license_info={"name": "MIT"},
)


@app.get("/v1/health", tags=["system"])
async def health_check():
    """Health check endpoint (no authentication required)."""
    return {"status": "healthy", "version": "0.1.0", "instance_id": settings.instance_id}


@app.get("/v1/status", tags=["system"])
async def system_status():
    """System status overview (requires authentication)."""
    return {
        "status": "success",
        "data": {
            "version": "0.1.0",
            "instance_id": settings.instance_id,
        },
    }


# Import and mount API routers
from monctl_central.api.router import api_router  # noqa: E402
app.include_router(api_router, prefix="/v1")


# ---------------------------------------------------------------------------
# Serve the frontend SPA (built React app)
# ---------------------------------------------------------------------------
_STATIC_DIR = Path(os.environ.get("MONCTL_STATIC_DIR", "/app/static"))

if _STATIC_DIR.exists() and (_STATIC_DIR / "index.html").exists():
    # Serve Vite-built assets (JS, CSS, images)
    _assets_dir = _STATIC_DIR / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """SPA fallback: serve static files or index.html for client-side routing."""
        file_path = _STATIC_DIR / full_path
        if full_path and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_STATIC_DIR / "index.html"))
