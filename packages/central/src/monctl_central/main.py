"""MonCTL Central Server - FastAPI application."""

from __future__ import annotations

import asyncio
import logging
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

# Apply configured log level to the stdlib root logger so that modules using
# `logging.getLogger(__name__)` (e.g. incidents/engine, events/engine,
# alerting/engine) actually emit at INFO. Without this call the stdlib root
# defaults to WARNING and info-level lines from those modules are silently
# dropped, making shadow-mode observability effectively blind.
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

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
    from monctl_central.storage.models import DeviceCategory, LabelKey, User

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

        # Seed device categories (name, description, category)
        _DEFAULT_DEVICE_CATEGORIES = [
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
            count = (await session.execute(select(DeviceCategory).limit(1))).scalar_one_or_none()
            if count is None:
                for name, description, category in _DEFAULT_DEVICE_CATEGORIES:
                    session.add(DeviceCategory(name=name, description=description, category=category))
                await session.commit()
                logger.info("device_categories_seeded", count=len(_DEFAULT_DEVICE_CATEGORIES))

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

        # Auto-import built-in packs (creates apps if they don't exist yet)
        # and auto-reconcile any pack whose on-disk content hash has
        # drifted from what we last imported. Matches how collectors
        # pick up app source changes — no operator step required.
        import hashlib
        from pathlib import Path
        import json as _json

        _pack_dirs = [
            Path("/app/packs"),
            Path(__file__).resolve().parents[4] / "packs",
        ]
        _pack_files: list[Path] = []
        _seen_names: set[str] = set()
        for d in _pack_dirs:
            if not d.is_dir():
                continue
            for p in sorted(d.glob("*.json")):
                if p.name in _seen_names:
                    continue
                _seen_names.add(p.name)
                _pack_files.append(p)
        for pack_path in _pack_files:
            pack_file = pack_path.name
            try:
                raw_bytes = pack_path.read_bytes()
                on_disk_hash = hashlib.sha256(raw_bytes).hexdigest()
                pack_data = _json.loads(raw_bytes)
                pack_uid = pack_data["pack_uid"]
                pack_version = pack_data["version"]

                from monctl_central.storage.models import Pack, PackVersion
                from monctl_central.packs.service import import_pack

                async with factory() as pack_session:
                    existing_pv = (await pack_session.execute(
                        select(PackVersion)
                        .join(Pack, PackVersion.pack_id == Pack.id)
                        .where(
                            Pack.pack_uid == pack_uid,
                            PackVersion.version == pack_version,
                        )
                    )).scalar_one_or_none()

                    if existing_pv is not None:
                        stored_hash = existing_pv.content_hash
                        if stored_hash == on_disk_hash:
                            # Same version, same bytes — nothing to do.
                            logger.debug("builtin_pack_unchanged pack=%s", pack_file)
                            continue
                        # Either first run after the column was added
                        # (stored_hash is NULL) or a genuine in-place
                        # edit. Either way: reconcile and backfill.
                        logger.warning(
                            "pack_content_drift_detected pack_uid=%s version=%s "
                            "old_hash=%s new_hash=%s",
                            pack_uid, pack_version,
                            stored_hash, on_disk_hash,
                        )
                        stats = await import_pack(
                            pack_data,
                            {"*": "reconcile"},
                            pack_session,
                            content_hash=on_disk_hash,
                        )
                        await pack_session.commit()
                        logger.info(
                            "builtin_pack_reconciled pack=%s diff=%s",
                            pack_file, stats.get("diff"),
                        )
                        continue

                    # Version not yet imported: fresh install with
                    # "skip" resolution so we never overwrite anything
                    # the operator renamed or edited. Then run reconcile
                    # to align any older-version defs with the new
                    # canonical content.
                    resolutions: dict[str, str] = {}
                    for app_item in pack_data.get("contents", {}).get("apps", []):
                        resolutions[f"apps:{app_item['name']}"] = "skip"
                    stats = await import_pack(
                        pack_data,
                        resolutions,
                        pack_session,
                        content_hash=on_disk_hash,
                    )
                    await pack_session.commit()
                    if stats.get("created", 0) > 0:
                        logger.info(
                            "builtin_pack_imported pack=%s stats=%s",
                            pack_file, stats,
                        )

                # After a fresh import of a NEW version, reconcile once
                # so pack-owned entities from older versions get aligned.
                async with factory() as reconcile_session:
                    diff_stats = await import_pack(
                        pack_data,
                        {"*": "reconcile"},
                        reconcile_session,
                        content_hash=on_disk_hash,
                    )
                    await reconcile_session.commit()
                    logger.debug(
                        "builtin_pack_post_import_reconcile pack=%s diff=%s",
                        pack_file, diff_stats.get("diff"),
                    )
            except Exception as exc:
                logger.warning("builtin_pack_import_failed", pack=pack_file, error=str(exc))

    # ── Seed default RBAC roles ────────────────────────────────────────────
    from monctl_central.storage.models import Role, RolePermission

    async with factory() as session:
        existing_role = (await session.execute(select(Role).limit(1))).scalar_one_or_none()
        if existing_role is None:
            viewer = Role(name="Viewer", description="Read-only access to all resources", is_system=True)
            session.add(viewer)
            await session.flush()
            for res in ["device", "app", "assignment", "credential", "alert", "automation",
                        "event", "connector", "collector",
                        "tenant", "user", "template", "settings", "result",
                        "api_key"]:
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
                ("automation", "view"), ("automation", "create"), ("automation", "edit"),
                ("event", "view"), ("event", "manage"),
                ("connector", "view"),
                ("collector", "view"),
                ("template", "view"), ("template", "create"), ("template", "edit"),
                ("result", "view"),
                ("api_key", "view"), ("api_key", "create"), ("api_key", "delete"),
            ]:
                session.add(RolePermission(role_id=operator.id, resource=res, action=act))

            await session.commit()
            logger.info("default_roles_seeded")
        else:
            # Ensure new resources are added to existing system roles
            _NEW_VIEWER_PERMS = [
                ("automation", "view"), ("event", "view"),
                ("connector", "view"),
                ("api_key", "view"),
            ]
            _NEW_OPERATOR_PERMS = [
                ("automation", "view"), ("automation", "create"), ("automation", "edit"),
                ("event", "view"), ("event", "manage"),
                ("connector", "view"),
                ("api_key", "view"), ("api_key", "create"), ("api_key", "delete"),
            ]
            for role_name, new_perms in [("Viewer", _NEW_VIEWER_PERMS), ("Operator", _NEW_OPERATOR_PERMS)]:
                db_role = (await session.execute(
                    select(Role).where(Role.name == role_name, Role.is_system.is_(True))
                )).scalar_one_or_none()
                if not db_role:
                    continue
                existing = {(p.resource, p.action) for p in (await session.execute(
                    select(RolePermission).where(RolePermission.role_id == db_role.id)
                )).scalars().all()}
                for res, act in new_perms:
                    if (res, act) not in existing:
                        session.add(RolePermission(role_id=db_role.id, resource=res, action=act))
                        logger.info("role_permission_added", role=role_name, resource=res, action=act)
            await session.commit()

    # ── Seed built-in connectors ────────────────────────────────────────────
    import hashlib
    from monctl_central.storage.models import Connector, ConnectorVersion

    # Source for built-in connectors lives in <repo>/connectors/*.py.
    # Mounted into the container image at /app/connectors. The seed runs only
    # on fresh installs; existing prod installs upload new versions via the
    # admin API (see _parse_semver guard below — newer seed versions log but
    # never auto-promote).
    _connector_dirs = [
        Path("/app/connectors"),
        Path(__file__).resolve().parents[4] / "connectors",
    ]
    def _read_connector_source(filename: str) -> str:
        for d in _connector_dirs:
            p = d / filename
            if p.is_file():
                return p.read_text()
        raise FileNotFoundError(f"built-in connector source missing: {filename}")

    _BUILTIN_CONNECTORS = [
        {
            "name": "snmp",
            "description": "SNMP v1/v2c/v3 connector \u2014 polls OIDs via PySNMP",
            "connector_type": "snmp",
            "version": "1.4.4",
            "entry_class": "SnmpConnector",
            "requirements": ["pysnmp>=7.1"],
            "source_code": _read_connector_source("snmp.py"),
        },
        {
            "name": "ssh",
            "description": "SSH connector \u2014 executes commands via asyncssh",
            "connector_type": "ssh",
            "version": "1.0.0",
            "entry_class": "SshConnector",
            "requirements": ["asyncssh>=2.14"],
            "source_code": _read_connector_source("ssh.py"),
        },
    ]


    def _parse_semver(v: str | None) -> tuple[int, ...]:
        import re as _re
        if not v:
            return (0,)
        parts = _re.findall(r"\d+", v)
        return tuple(int(p) for p in parts) if parts else (0,)

    async with factory() as session:
        for spec in _BUILTIN_CONNECTORS:
            existing = (await session.execute(
                select(Connector).where(Connector.name == spec["name"])
            )).scalar_one_or_none()

            src_checksum = hashlib.sha256(spec["source_code"].encode()).hexdigest()

            if existing is None:
                # Fresh DB: seed the connector + initial version.
                connector = Connector(
                    name=spec["name"],
                    description=spec["description"],
                    connector_type=spec["connector_type"],
                    is_builtin=True,
                )
                session.add(connector)
                await session.flush()
                version = ConnectorVersion(
                    connector_id=connector.id,
                    version=spec["version"],
                    source_code=spec["source_code"],
                    requirements=spec.get("requirements"),
                    entry_class=spec["entry_class"],
                    is_latest=True,
                    checksum=src_checksum,
                )
                session.add(version)
                logger.info("connector_seeded", name=spec["name"],
                            version=spec["version"])
                continue

            # Existing connector: never mutate the installed is_latest
            # source_code. Operators upload newer versions through the
            # admin API (and promote them via is_latest). The seed is
            # purely fresh-install bootstrap. Blindly syncing the seed's
            # source over an uploaded newer version would silently revert
            # fleet-wide features (see feedback_check_memory_before_writing_code).
            latest_stmt = select(ConnectorVersion).where(
                ConnectorVersion.connector_id == existing.id,
                ConnectorVersion.is_latest == True,  # noqa: E712
            )
            latest_ver = (await session.execute(latest_stmt)).scalar_one_or_none()
            if latest_ver is None:
                # No is_latest row — recover by inserting the seed version
                # as is_latest so the fleet has something to pull.
                version = ConnectorVersion(
                    connector_id=existing.id,
                    version=spec["version"],
                    source_code=spec["source_code"],
                    requirements=spec.get("requirements"),
                    entry_class=spec["entry_class"],
                    is_latest=True,
                    checksum=src_checksum,
                )
                session.add(version)
                logger.warning(
                    "connector_reseeded_no_latest",
                    name=spec["name"], version=spec["version"],
                )
                continue

            seed_v = _parse_semver(spec["version"])
            installed_v = _parse_semver(latest_ver.version)
            if seed_v > installed_v:
                # Seed has a newer version than what's installed. We do NOT
                # auto-promote — just surface it so ops can upload + promote
                # deliberately. This breaks the silent-downgrade footgun.
                logger.warning(
                    "connector_seed_newer_than_installed",
                    name=spec["name"],
                    seed_version=spec["version"],
                    installed_version=latest_ver.version,
                    hint="Upload the new version via POST /v1/connectors/{id}/versions",
                )
            elif latest_ver.checksum != src_checksum:
                # Same-or-older seed, but source drifted — almost certainly
                # because an operator uploaded patched source under the same
                # version label. Log for audit; do NOT overwrite.
                logger.info(
                    "connector_seed_drift_detected",
                    name=spec["name"],
                    installed_version=latest_ver.version,
                    seed_version=spec["version"],
                )

        await session.commit()

    # ── Seed app-level connector bindings ─────────────────────────────────
    from monctl_central.storage.models import App, AppConnectorBinding

    _APP_CONNECTOR_REQUIREMENTS: dict[str, list[str]] = {
        "snmp_check": ["snmp"],
        "snmp_interface_poller": ["snmp"],
        "snmp_discovery": ["snmp"],
    }

    async with factory() as session:
        for app_name, connector_names in _APP_CONNECTOR_REQUIREMENTS.items():
            app = (await session.execute(
                select(App).where(App.name == app_name)
            )).scalar_one_or_none()
            if app is None:
                continue
            for connector_name in connector_names:
                connector = (await session.execute(
                    select(Connector).where(Connector.name == connector_name)
                )).scalar_one_or_none()
                if connector is None:
                    continue
                existing = (await session.execute(
                    select(AppConnectorBinding).where(
                        AppConnectorBinding.app_id == app.id,
                        AppConnectorBinding.connector_type == connector.connector_type,
                    )
                )).scalar_one_or_none()
                if existing:
                    continue
                session.add(AppConnectorBinding(
                    app_id=app.id,
                    connector_id=connector.id,
                    connector_type=connector.connector_type,
                ))
                logger.info("app_connector_binding_seeded",
                            app=app_name, connector_type=connector.connector_type)
        await session.commit()

    # ── ClickHouse schema init ─────────────────────────────────────────────
    from monctl_central.dependencies import get_clickhouse

    ch = None
    try:
        ch = get_clickhouse()
        ch.ensure_tables()
        logger.info("clickhouse_tables_ensured")
    except Exception:
        logger.warning("clickhouse_init_failed", exc_info=True)

    # Register this central node's version
    import os as _os
    import platform as _platform
    import socket as _socket
    from monctl_central.storage.models import SystemVersion

    async with factory() as session:
        _hostname = (
            _os.environ.get("MONCTL_NODE_NAME")
            or settings.node_name
            or settings.instance_id
            or _socket.gethostname()
        )
        sv = (await session.execute(
            select(SystemVersion).where(SystemVersion.node_hostname == _hostname)
        )).scalar_one_or_none()
        if not sv:
            sv = SystemVersion(
                node_hostname=_hostname,
                node_role="central",
                node_ip="",
            )
            session.add(sv)
        _node_ip = _os.environ.get("MONCTL_NODE_IP") or _socket.gethostbyname(_socket.gethostname())
        sv.node_ip = _node_ip
        sv.monctl_version = "0.1.0"
        sv.os_version = f"{_platform.system()} {_platform.release()}"
        sv.kernel_version = _platform.release()
        sv.python_version = _platform.python_version()
        from monctl_common.utils import utc_now
        sv.last_reported_at = utc_now()
        await session.commit()
        logger.info("central_version_registered", hostname=_hostname)

    # ── ClickHouse write buffer ───────────────────────────────────────────
    ch_buffer = None
    if ch is not None:
        from monctl_central.storage import ch_buffer as _ch_buf_mod
        from monctl_central.storage.ch_buffer import ClickHouseWriteBuffer
        ch_buffer = ClickHouseWriteBuffer(ch)
        await ch_buffer.start()
        _ch_buf_mod._buffer = ch_buffer
        logger.info("ch_write_buffer_started")

    # ── Redis connection ───────────────────────────────────────────────────
    from monctl_central.cache import get_redis

    try:
        await get_redis(
            settings.redis_url,
            sentinel_hosts=settings.redis_sentinel_hosts,
            sentinel_master=settings.redis_sentinel_master,
        )
        logger.info("redis_connected")
    except Exception:
        logger.warning("redis_connect_failed", exc_info=True)

    # ── TLS cert sync (runs on ALL nodes, not leader-gated) ─────────────
    cert_sync_task = None
    try:
        from monctl_central.tls.sync import run_cert_sync_loop
        cert_sync_task = asyncio.create_task(run_cert_sync_loop(factory))
        logger.info("tls_cert_sync_started")
    except Exception:
        logger.warning("tls_cert_sync_start_failed", exc_info=True)

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

    # Start audit buffer (batched ClickHouse insert for mutation audit)
    try:
        from monctl_central.audit.buffer import audit_buffer
        from monctl_central.audit.db_events import install_listeners as install_audit_listeners

        install_audit_listeners()
        audit_buffer.start()
        logger.info("audit_buffer_started")
    except Exception:
        logger.warning("audit_buffer_start_failed", exc_info=True)

    # ── WebSocket command listener (cross-node broadcast via Redis) ────────
    ws_cmd_listener_task = None
    try:
        from monctl_central.ws.router import manager as ws_manager
        ws_cmd_listener_task = await ws_manager.start_command_listener()
    except Exception:
        logger.warning("ws_cmd_listener_start_failed", exc_info=True)

    yield

    # Shutdown
    if ws_cmd_listener_task:
        ws_cmd_listener_task.cancel()
        try:
            await ws_cmd_listener_task
        except asyncio.CancelledError:
            pass

    if cert_sync_task:
        cert_sync_task.cancel()
        try:
            await cert_sync_task
        except asyncio.CancelledError:
            pass

    if scheduler_runner:
        await scheduler_runner.stop()
    if leader:
        await leader.stop()

    if ch_buffer:
        await ch_buffer.stop()

    try:
        from monctl_central.audit.buffer import audit_buffer
        await audit_buffer.stop()
    except Exception:
        logger.warning("audit_buffer_stop_failed", exc_info=True)

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
    {"name": "alerting",    "description": "App-level alert definitions, instances, and threshold overrides."},
    {"name": "events",      "description": "Events and event policies. Events are promoted from alerts via configurable policies."},
    {"name": "upgrades", "description": "System upgrade management. Upload bundles, orchestrate rolling upgrades, manage OS patches."},
    {"name": "dashboard", "description": "Aggregated dashboard data for operational overview."},
    {"name": "automations", "description": "Run Book Automation: actions, automations, and run history."},
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

# Structured validation error responses
from fastapi.exceptions import RequestValidationError  # noqa: E402
from monctl_central.validation import validation_exception_handler  # noqa: E402
app.add_exception_handler(RequestValidationError, validation_exception_handler)

# Audit middleware — populates request-scoped AuditContext and flushes
# mutation rows buffered during the request to ClickHouse.
from monctl_central.audit.middleware import AuditContextMiddleware  # noqa: E402
app.add_middleware(AuditContextMiddleware)


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

# WebSocket router — mounted at app root (not under /v1/)
from monctl_central.ws.router import router as ws_router  # noqa: E402
app.include_router(ws_router)

# Collector API — job-pull model (new distributed collector system)
from monctl_central.collector_api.router import router as collector_api_router  # noqa: E402
app.include_router(collector_api_router, prefix="/api/v1")

# Docker stats push endpoint (worker sidecars → central)
from monctl_central.collector_api.docker_push import router as docker_push_router  # noqa: E402
app.include_router(docker_push_router, prefix="/api/v1")


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
