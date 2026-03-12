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


def _get_default_apps():
    """Return list of (name, description, source_code, entry_class, requirements) for default apps."""
    ping_check_code = '''\
"""ICMP ping check — measures reachability and round-trip time."""
import asyncio
import time
from monctl_collector.polling.base import BasePoller
from monctl_collector.jobs.models import PollContext, PollResult


class Poller(BasePoller):
    async def poll(self, context: PollContext) -> PollResult:
        host = context.device_host or context.parameters.get("host", "")
        count = context.parameters.get("count", 3)
        timeout = context.parameters.get("timeout", 5)
        start = time.time()

        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", str(count), "-W", str(timeout), host,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout * count + 5
            )
            output = stdout.decode()
            execution_ms = int((time.time() - start) * 1000)

            if proc.returncode == 0:
                rtt = self._parse_rtt(output)
                loss = self._parse_loss(output)
                return PollResult(
                    job_id=context.job.job_id,
                    device_id=context.job.device_id,
                    collector_node=context.node_id,
                    timestamp=time.time(),
                    metrics=[
                        {"name": "rtt_ms", "value": rtt},
                        {"name": "packet_loss_pct", "value": loss},
                    ],
                    config_data=None,
                    status="ok" if loss < 100 else "critical",
                    reachable=True,
                    error_message=None,
                    execution_time_ms=execution_ms,
                    rtt_ms=rtt,
                )
            else:
                return PollResult(
                    job_id=context.job.job_id,
                    device_id=context.job.device_id,
                    collector_node=context.node_id,
                    timestamp=time.time(),
                    metrics=[{"name": "packet_loss_pct", "value": 100.0}],
                    config_data=None,
                    status="critical",
                    reachable=False,
                    error_message=f"Ping failed: {stderr.decode().strip() or 'no response'}",
                    execution_time_ms=execution_ms,
                )
        except asyncio.TimeoutError:
            execution_ms = int((time.time() - start) * 1000)
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[],
                config_data=None,
                status="critical",
                reachable=False,
                error_message=f"Ping timed out after {timeout * count}s",
                execution_time_ms=execution_ms,
            )

    def _parse_rtt(self, output: str) -> float:
        """Extract avg RTT from ping output."""
        for line in output.splitlines():
            if "avg" in line and "/" in line:
                parts = line.split("=")
                if len(parts) >= 2:
                    vals = parts[-1].strip().split("/")
                    if len(vals) >= 2:
                        try:
                            return float(vals[1])
                        except ValueError:
                            pass
        return 0.0

    def _parse_loss(self, output: str) -> float:
        """Extract packet loss percentage from ping output."""
        for line in output.splitlines():
            if "packet loss" in line or "loss" in line:
                for part in line.split(","):
                    part = part.strip()
                    if "%" in part:
                        try:
                            return float(part.split("%")[0].strip().split()[-1])
                        except (ValueError, IndexError):
                            pass
        return 0.0
'''

    port_check_code = '''\
"""TCP port check — tests if a port is open and measures response time."""
import asyncio
import time
from monctl_collector.polling.base import BasePoller
from monctl_collector.jobs.models import PollContext, PollResult


class Poller(BasePoller):
    async def poll(self, context: PollContext) -> PollResult:
        host = context.device_host or context.parameters.get("host", "")
        port = int(context.parameters.get("port", 443))
        timeout = context.parameters.get("timeout", 5)
        start = time.time()

        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout,
            )
            response_ms = round((time.time() - start) * 1000, 2)
            writer.close()
            await writer.wait_closed()
            execution_ms = int((time.time() - start) * 1000)

            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[
                    {"name": "response_time_ms", "value": response_ms},
                    {"name": "port_open", "value": 1},
                ],
                config_data=None,
                status="ok",
                reachable=True,
                error_message=None,
                execution_time_ms=execution_ms,
                response_time_ms=response_ms,
            )
        except (asyncio.TimeoutError, OSError, ConnectionRefusedError) as exc:
            execution_ms = int((time.time() - start) * 1000)
            is_timeout = isinstance(exc, asyncio.TimeoutError)
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[{"name": "port_open", "value": 0}],
                config_data=None,
                status="critical",
                reachable=False,
                error_message=f"Port {port} {'timed out' if is_timeout else 'refused/unreachable'}: {exc}",
                execution_time_ms=execution_ms,
            )
'''

    snmp_check_code = '''\
"""SNMP check placeholder — requires pysnmp for full implementation."""
import time
from monctl_collector.polling.base import BasePoller
from monctl_collector.jobs.models import PollContext, PollResult


class Poller(BasePoller):
    async def poll(self, context: PollContext) -> PollResult:
        return PollResult(
            job_id=context.job.job_id,
            device_id=context.job.device_id,
            collector_node=context.node_id,
            timestamp=time.time(),
            metrics=[],
            config_data=None,
            status="unknown",
            reachable=False,
            error_message="SNMP check not yet implemented — upload source code via PUT /api/v1/apps/snmp_check/code",
            execution_time_ms=0,
        )
'''

    return [
        ("ping_check", "ICMP ping check", ping_check_code, "Poller", [], {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "title": "Packet Count", "default": 3, "minimum": 1, "maximum": 20},
                "timeout": {"type": "integer", "title": "Timeout (s)", "default": 2, "minimum": 1, "maximum": 30},
            },
        }),
        ("port_check", "TCP port check", port_check_code, "Poller", [], {
            "type": "object",
            "properties": {
                "port": {"type": "integer", "title": "Port", "default": 443, "minimum": 1, "maximum": 65535},
            },
        }),
        ("snmp_check", "SNMP check (v1/v2c/v3)", snmp_check_code, "Poller", [], {
            "type": "object",
            "properties": {
                "oid": {"type": "string", "title": "OID", "x-widget": "snmp-oid"},
                "snmp_credential": {"type": "string", "title": "Credential", "x-widget": "credential"},
            },
        }),
    ]


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
    from monctl_central.storage.models import App, AppVersion, DeviceType, User

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

        # Seed default apps with source code
        _DEFAULT_APPS = _get_default_apps()
        async with factory() as session:
            for app_name, desc, source_code, entry_class, requirements, config_schema in _DEFAULT_APPS:
                existing_app = (
                    await session.execute(select(App).where(App.name == app_name))
                ).scalar_one_or_none()
                if existing_app is None:
                    app_obj = App(
                        name=app_name, description=desc, app_type="script",
                        config_schema=config_schema,
                    )
                    session.add(app_obj)
                    await session.flush()
                    import hashlib as _hl
                    checksum = _hl.sha256(source_code.encode()).hexdigest()
                    session.add(AppVersion(
                        app_id=app_obj.id,
                        version="1.0.0",
                        checksum_sha256=checksum,
                        source_code=source_code,
                        entry_class=entry_class,
                        requirements=requirements,
                    ))
                else:
                    # Update existing app: backfill config_schema if missing
                    if existing_app.config_schema is None and config_schema:
                        existing_app.config_schema = config_schema
                    # Update existing app version if source_code is missing
                    from sqlalchemy.orm import selectinload
                    stmt = select(App).options(selectinload(App.versions)).where(App.name == app_name)
                    app_row = (await session.execute(stmt)).scalar_one_or_none()
                    if app_row and app_row.versions:
                        v = app_row.versions[0]
                        if not v.source_code:
                            import hashlib as _hl
                            v.source_code = source_code
                            v.entry_class = entry_class
                            v.requirements = requirements
                            v.checksum_sha256 = _hl.sha256(source_code.encode()).hexdigest()
            await session.commit()
            logger.info("default_apps_seeded")

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
