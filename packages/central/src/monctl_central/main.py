"""MonCTL Central Server - FastAPI application."""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
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

    role = settings.role  # "api", "scheduler", or "all"
    logger.info(
        "central_starting",
        instance_id=settings.instance_id,
        role=role,
        host=settings.host,
        port=settings.port,
    )

    from sqlalchemy import select
    from monctl_central.storage.models import DeviceType, LabelKey, User

    factory = get_session_factory()

    # Seed defaults (only on api/all roles)
    if role in ("api", "all"):
        # Seed admin user
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

        # Seed device types (name, description, category)
        _DEFAULT_DEVICE_TYPES = [
            ("host", "Generic server, VM, or physical machine", "server"),
            ("network", "Network device — router, switch, firewall, access point", "network"),
            ("api", "HTTP API endpoint or web service", "service"),
            ("database", "Database server — PostgreSQL, MySQL, Redis, etc.", "database"),
            ("service", "Application service or microservice", "service"),
            ("container", "Docker container or Kubernetes pod", "server"),
            ("virtual-machine", "Hypervisor-managed virtual machine", "server"),
            ("storage", "Storage array, NAS, or SAN device", "storage"),
            ("printer", "Printer or print server", "printer"),
            ("iot", "IoT or embedded device", "iot"),
        ]
        async with factory() as session:
            count = (await session.execute(select(DeviceType).limit(1))).scalar_one_or_none()
            if count is None:
                for name, description, category in _DEFAULT_DEVICE_TYPES:
                    session.add(DeviceType(name=name, description=description, category=category))
                await session.commit()
                logger.info("device_types_seeded", count=len(_DEFAULT_DEVICE_TYPES))

        # Seed default label keys
        async with factory() as session:
            existing_lk = (await session.execute(select(LabelKey).limit(1))).scalar_one_or_none()
            if existing_lk is None:
                default_label_keys = [
                    LabelKey(key="site", description="Lokation", show_description=True,
                             predefined_values=["aarhus", "copenhagen"]),
                    LabelKey(key="env", description="Miljø", show_description=True,
                             predefined_values=["production", "staging", "development", "test"]),
                    LabelKey(key="role", description="Rolle", show_description=True,
                             predefined_values=["web", "db", "cache", "proxy", "monitoring"]),
                    LabelKey(key="owner", description="Ansvarlig", show_description=True),
                    LabelKey(key="criticality", description="Kritikalitet", show_description=True,
                             predefined_values=["critical", "high", "medium", "low"]),
                ]
                session.add_all(default_label_keys)
                await session.commit()
                logger.info("label_keys_seeded", count=len(default_label_keys))

        # Apps are managed entirely via the web UI — no seed apps on startup.

    # ── Seed default RBAC roles ────────────────────────────────────────────
    from monctl_central.storage.models import Role, RolePermission

    async with factory() as session:
        existing_role = (await session.execute(select(Role).limit(1))).scalar_one_or_none()
        if existing_role is None:
            viewer = Role(name="Viewer", description="Read-only access to all resources", is_system=True)
            session.add(viewer)
            await session.flush()
            for res in ["device", "app", "assignment", "credential", "alert", "collector",
                        "tenant", "user", "template", "settings", "result"]:
                session.add(RolePermission(role_id=viewer.id, resource=res, action="view"))

            operator = Role(
                name="Operator",
                description="Can view and edit devices, apps, and assignments",
                is_system=True,
            )
            session.add(operator)
            await session.flush()
            for res, act in [
                ("device", "view"), ("device", "create"), ("device", "edit"),
                ("app", "view"), ("app", "create"), ("app", "edit"),
                ("assignment", "view"), ("assignment", "create"), ("assignment", "edit"),
                ("credential", "view"),
                ("alert", "view"), ("alert", "create"), ("alert", "edit"),
                ("collector", "view"),
                ("template", "view"), ("template", "create"), ("template", "edit"),
                ("result", "view"),
            ]:
                session.add(RolePermission(role_id=operator.id, resource=res, action=act))

            await session.commit()
            logger.info("default_roles_seeded")

    # ── ClickHouse schema init ─────────────────────────────────────────────
    from monctl_central.dependencies import get_clickhouse

    ch = None
    try:
        ch = get_clickhouse()
        ch.ensure_tables()
        logger.info("clickhouse_tables_ensured")
    except Exception:
        logger.warning("clickhouse_init_failed", exc_info=True)

    # ── Redis connection ───────────────────────────────────────────────────
    from monctl_central.cache import get_redis

    try:
        await get_redis(settings.redis_url)
        logger.info("redis_connected")
    except Exception:
        logger.warning("redis_connect_failed", exc_info=True)

    # ── Scheduler with leader election (health monitor + alert engine) ─────
    leader = None
    scheduler_runner = None
    if role in ("scheduler", "all"):
        try:
            from monctl_central.cache import _redis
            from monctl_central.scheduler.leader import LeaderElection
            from monctl_central.scheduler.tasks import SchedulerRunner

            if _redis is not None:
                leader = LeaderElection(_redis, settings.instance_id)
                await leader.start()
                scheduler_runner = SchedulerRunner(
                    leader=leader,
                    session_factory=factory,
                    clickhouse_client=ch,
                )
                await scheduler_runner.start()
                logger.info("scheduler_started", instance_id=settings.instance_id)
            else:
                logger.warning("scheduler_skipped_no_redis")
        except Exception:
            logger.warning("scheduler_start_failed", exc_info=True)

    yield

    # Shutdown
    if scheduler_runner:
        await scheduler_runner.stop()
    if leader:
        await leader.stop()

    from monctl_central.cache import close_redis
    await close_redis()

    if ch:
        ch.close()

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

# Collector API — job-pull model (new distributed collector system)
from monctl_central.collector_api.router import router as collector_api_router  # noqa: E402
app.include_router(collector_api_router, prefix="/api/v1")


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
