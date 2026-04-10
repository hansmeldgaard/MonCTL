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
        from pathlib import Path
        import json as _json

        _BUILTIN_PACKS = ["snmp-core-v1.0.0.json", "basic-checks-v1.0.0.json"]
        _pack_dirs = [
            Path("/app/packs"),
            Path(__file__).resolve().parents[4] / "packs",
        ]
        for pack_file in _BUILTIN_PACKS:
            pack_path = None
            for d in _pack_dirs:
                candidate = d / pack_file
                if candidate.exists():
                    pack_path = candidate
                    break
            if pack_path is None:
                continue
            try:
                pack_data = _json.loads(pack_path.read_text())
                pack_uid = pack_data["pack_uid"]
                pack_version = pack_data["version"]

                # Skip if this pack version was already imported
                from monctl_central.storage.models import Pack, PackVersion
                async with factory() as pack_session:
                    existing = (await pack_session.execute(
                        select(PackVersion)
                        .join(Pack, PackVersion.pack_id == Pack.id)
                        .where(Pack.pack_uid == pack_uid, PackVersion.version == pack_version)
                    )).scalar_one_or_none()
                    if existing:
                        continue

                from monctl_central.packs.service import import_pack
                # "skip" resolution: create missing apps, don't overwrite existing
                resolutions = {}
                for app_item in pack_data.get("contents", {}).get("apps", []):
                    resolutions[f"apps:{app_item['name']}"] = "skip"
                async with factory() as pack_session:
                    stats = await import_pack(pack_data, resolutions, pack_session)
                    await pack_session.commit()
                if stats["created"] > 0:
                    logger.info("builtin_pack_imported", pack=pack_file, **stats)
                else:
                    logger.debug("builtin_pack_skipped", pack=pack_file)
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
                        "event", "connector", "dashboard", "collector",
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
                ("dashboard", "view"), ("dashboard", "create"), ("dashboard", "edit"),
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
                ("connector", "view"), ("dashboard", "view"),
                ("api_key", "view"),
            ]
            _NEW_OPERATOR_PERMS = [
                ("automation", "view"), ("automation", "create"), ("automation", "edit"),
                ("event", "view"), ("event", "manage"),
                ("connector", "view"),
                ("dashboard", "view"), ("dashboard", "create"), ("dashboard", "edit"),
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

    _BUILTIN_CONNECTORS = [
        {
            "name": "snmp",
            "description": "SNMP v2c/v3 connector — polls OIDs via PySNMP",
            "connector_type": "snmp",
            "version": "1.3.0",
            "entry_class": "SnmpConnector",
            "requirements": ["pysnmp>=7.1"],
            "source_code": '''\
"""Built-in SNMP connector for MonCTL.

Supports SNMP v1, v2c, and v3 via pysnmp 7.x async API.

v1.3.0: Fix UDP socket leak — reuse SnmpEngine + UdpTransportTarget across
        all operations within a single connect/close lifecycle instead of
        creating new ones per get/walk call.

Credential keys (v1/v2c):
    snmp_version   "1" or "2c" (default "2c")
    community      Community string (default "public")

Credential keys (v3):
    snmp_version    "3"
    username        USM username
    auth_protocol   "MD5", "SHA", "SHA224", "SHA256", "SHA384", "SHA512", or ""
    auth_password   Auth passphrase
    priv_protocol   "DES", "3DES", "AES", "AES192", "AES256", or ""
    priv_password   Privacy passphrase
    security_level  "noauthnopriv", "authnopriv", or "authpriv" (default "authpriv")

Settings keys:
    port      SNMP port (default 161)
    timeout   Timeout in seconds (default 5)
    retries   Retry count (default 2)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_AUTH_PROTOCOLS = {
    "MD5": "usmHMACMD5AuthProtocol",
    "SHA": "usmHMACSHAAuthProtocol",
    "SHA224": "usmHMAC128SHA224AuthProtocol",
    "SHA256": "usmHMAC192SHA256AuthProtocol",
    "SHA384": "usmHMAC256SHA384AuthProtocol",
    "SHA512": "usmHMAC384SHA512AuthProtocol",
}

_PRIV_PROTOCOLS = {
    "DES": "usmDESPrivProtocol",
    "3DES": "usm3DESEDEPrivProtocol",
    "AES": "usmAesCfb128Protocol",
    "AES192": "usmAesCfb192Protocol",
    "AES256": "usmAesCfb256Protocol",
}


class SnmpConnector:
    """SNMP v1/v2c/v3 connector that polls OIDs from a target device."""

    def __init__(self, settings: dict[str, Any], credential: dict[str, Any] | None = None):
        self.settings = settings
        self.credential = credential or {}
        self.version = str(self.credential.get("snmp_version", "2c")).lower()
        self.port = int(self.settings.get("port", 161))
        self.timeout = int(self.settings.get("timeout", 5))
        self.retries = int(self.settings.get("retries", 2))
        self._host: str = ""
        self._engine = None
        self._transport = None
        self._auth = None

    def _build_auth(self):
        """Build the appropriate pysnmp auth object for the configured version."""
        if self.version == "3":
            return self._build_v3_auth()
        return self._build_v1v2c_auth()

    def _build_v1v2c_auth(self):
        from pysnmp.hlapi.v3arch.asyncio import CommunityData
        community = self.credential.get("community", "public")
        mp_model = 0 if self.version == "1" else 1
        return CommunityData(community, mpModel=mp_model)

    def _build_v3_auth(self):
        from pysnmp.hlapi.v3arch.asyncio import UsmUserData
        import pysnmp.hlapi.v3arch.asyncio as hlapi

        username = self.credential.get("username", "")
        auth_proto_name = (self.credential.get("auth_protocol") or "").upper()
        auth_key = self.credential.get("auth_password", "")
        priv_proto_name = (self.credential.get("priv_protocol") or "").upper()
        priv_key = self.credential.get("priv_password", "")
        security_level = (self.credential.get("security_level") or "authpriv").lower()

        auth_proto = None
        if auth_proto_name in _AUTH_PROTOCOLS:
            auth_proto = getattr(hlapi, _AUTH_PROTOCOLS[auth_proto_name], None)

        priv_proto = None
        if priv_proto_name in _PRIV_PROTOCOLS:
            priv_proto = getattr(hlapi, _PRIV_PROTOCOLS[priv_proto_name], None)

        kwargs: dict[str, Any] = {"userName": username}

        if security_level == "noauthnopriv":
            return UsmUserData(**kwargs)

        if auth_proto and auth_key:
            kwargs["authKey"] = auth_key
            kwargs["authProtocol"] = auth_proto

        if security_level == "authpriv" and priv_proto and priv_key and auth_proto:
            kwargs["privKey"] = priv_key
            kwargs["privProtocol"] = priv_proto

        return UsmUserData(**kwargs)

    async def connect(self, host: str) -> None:
        """Create SNMP engine + transport — reused for all operations until close()."""
        # Idempotent: if already connected to same host, reuse. If different host
        # or called again (e.g. by apps that predate engine-managed lifecycle),
        # close the previous engine first to prevent memory leaks.
        if self._engine is not None:
            if self._host == host:
                return  # Already connected to this host
            await self.close()
        from pysnmp.hlapi.v3arch.asyncio import SnmpEngine, UdpTransportTarget
        self._host = host
        self._engine = SnmpEngine()
        self._transport = await UdpTransportTarget.create(
            (host, self.port), timeout=self.timeout, retries=self.retries,
        )
        self._auth = self._build_auth()
        logger.debug("snmp_connect host=%s port=%s version=%s", host, self.port, self.version)

    async def get(self, oids: list[str]) -> dict[str, Any]:
        """Perform SNMP GET for a list of OID strings."""
        from pysnmp.hlapi.v3arch.asyncio import (
            ContextData, ObjectIdentity, ObjectType, get_cmd,
        )
        obj_types = [ObjectType(ObjectIdentity(oid)) for oid in oids]
        error_indication, error_status, error_index, var_binds = await get_cmd(
            self._engine, self._auth, self._transport, ContextData(), *obj_types,
        )
        if error_indication:
            raise RuntimeError(f"SNMP error: {error_indication}")
        if error_status:
            raise RuntimeError(f"SNMP error at {error_index}: {error_status.prettyPrint()}")
        result: dict[str, Any] = {}
        for oid_val, val in var_binds:
            result[str(oid_val)] = val.prettyPrint()
        return result

    async def get_many(self, oid_batches: list[list[str]]) -> dict[str, Any]:
        """Execute multiple SNMP GET batches reusing the same session."""
        from pysnmp.hlapi.v3arch.asyncio import (
            ContextData, ObjectIdentity, ObjectType, get_cmd,
        )
        result: dict[str, Any] = {}
        for batch in oid_batches:
            try:
                obj_types = [ObjectType(ObjectIdentity(oid)) for oid in batch]
                err_ind, err_st, err_idx, var_binds = await get_cmd(
                    self._engine, self._auth, self._transport, ContextData(), *obj_types,
                )
                if not err_ind and not err_st:
                    for oid_val, val in var_binds:
                        result[str(oid_val)] = val.prettyPrint()
            except Exception:
                continue
        return result

    async def walk(self, oid: str) -> list[tuple[str, Any]]:
        """Perform SNMP WALK (GETBULK) with numeric OID boundary checking."""
        from pysnmp.hlapi.v3arch.asyncio import (
            ContextData, ObjectIdentity, ObjectType, bulk_cmd,
        )
        rows: list[tuple[str, Any]] = []
        current_oid = oid
        base_tuple = tuple(int(x) for x in oid.split("."))
        base_len = len(base_tuple)

        while len(rows) < 10000:
            error_indication, error_status, error_index, var_bind_table = await bulk_cmd(
                self._engine, self._auth, self._transport, ContextData(), 0, 25,
                ObjectType(ObjectIdentity(current_oid)),
            )
            if error_indication or error_status:
                break
            if not var_bind_table:
                break
            out_of_tree = False
            last_oid = None
            for name, val in var_bind_table:
                oid_tuple = tuple(name)
                if oid_tuple[:base_len] != base_tuple:
                    out_of_tree = True
                    break
                name_str = str(name)
                rows.append((name_str, val.prettyPrint()))
                last_oid = name_str
            if out_of_tree or last_oid is None or last_oid == current_oid:
                break
            current_oid = last_oid
        return rows

    async def close(self) -> None:
        """Close SNMP engine and release all internal pysnmp state."""
        if self._engine is not None:
            try:
                self._engine.close_dispatcher()
            except Exception:
                pass
            # Clear internal MIB/security registrations that accumulate
            try:
                mib = self._engine.get_mib_builder()
                mib.clean()
            except Exception:
                pass
            self._engine = None
        self._transport = None
        self._auth = None
''',
        },
        {
            "name": "ssh",
            "description": "SSH connector — executes commands via asyncssh",
            "connector_type": "ssh",
            "version": "1.0.0",
            "entry_class": "SshConnector",
            "requirements": ["asyncssh>=2.14"],
            "source_code": '''\
"""Built-in SSH connector for MonCTL."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SshConnector:
    """SSH connector that executes commands on a remote host."""

    def __init__(self, settings: dict[str, Any], credential: dict[str, Any] | None = None):
        self.settings = settings
        self.credential = credential or {}
        self.username = self.credential.get("username", "root")
        self.password = self.credential.get("password")
        self.private_key = self.credential.get("private_key")
        self.port = int(self.settings.get("port", 22))
        self.timeout = int(self.settings.get("timeout", 10))
        self._conn = None

    async def connect(self, host: str) -> None:
        """Open an SSH connection to the given host."""
        import asyncssh

        kwargs: dict[str, Any] = {
            "host": host,
            "port": self.port,
            "username": self.username,
            "known_hosts": None,
            "login_timeout": self.timeout,
        }
        if self.private_key:
            kwargs["client_keys"] = [asyncssh.import_private_key(self.private_key)]
        elif self.password:
            kwargs["password"] = self.password

        self._conn = await asyncssh.connect(**kwargs)
        logger.debug("ssh_connected", host=host, port=self.port, user=self.username)

    async def run(self, command: str) -> dict[str, Any]:
        """Execute a command and return stdout, stderr, and exit_status."""
        if self._conn is None:
            raise RuntimeError("Not connected — call connect() first")
        result = await self._conn.run(command, timeout=self.timeout)
        return {
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "exit_status": result.exit_status,
        }

    async def close(self) -> None:
        """Close the SSH connection."""
        if self._conn is not None:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None
''',
        },
    ]

    async with factory() as session:
        for spec in _BUILTIN_CONNECTORS:
            existing = (await session.execute(
                select(Connector).where(Connector.name == spec["name"])
            )).scalar_one_or_none()

            src_checksum = hashlib.sha256(spec["source_code"].encode()).hexdigest()

            if existing is None:
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
                logger.info("connector_seeded", name=spec["name"])
            else:
                # Sync source_code if checksum differs on the latest version
                latest_stmt = select(ConnectorVersion).where(
                    ConnectorVersion.connector_id == existing.id,
                    ConnectorVersion.is_latest == True,  # noqa: E712
                )
                latest_ver = (await session.execute(latest_stmt)).scalar_one_or_none()
                needs_update = (
                    latest_ver
                    and (
                        latest_ver.checksum != src_checksum
                        or latest_ver.requirements != spec.get("requirements")
                    )
                )
                if needs_update:
                    latest_ver.source_code = spec["source_code"]
                    latest_ver.checksum = src_checksum
                    latest_ver.requirements = spec.get("requirements")
                    latest_ver.entry_class = spec["entry_class"]
                    # Only update version string if it won't violate unique constraint
                    if latest_ver.version == spec["version"] or latest_ver.version is None:
                        latest_ver.version = spec["version"]
                    logger.info("connector_updated", name=spec["name"],
                                version=latest_ver.version)

        await session.commit()

    # ── Seed app-level connector bindings ─────────────────────────────────
    from monctl_central.storage.models import App, AppConnectorBinding

    _APP_CONNECTOR_REQUIREMENTS: dict[str, list[dict[str, str]]] = {
        "snmp_check": [{"alias": "snmp", "connector_name": "snmp"}],
        "snmp_interface_poller": [{"alias": "snmp", "connector_name": "snmp"}],
        "snmp_discovery": [{"alias": "snmp", "connector_name": "snmp"}],
    }

    async with factory() as session:
        for app_name, bindings in _APP_CONNECTOR_REQUIREMENTS.items():
            app = (await session.execute(
                select(App).where(App.name == app_name)
            )).scalar_one_or_none()
            if app is None:
                continue
            for binding_spec in bindings:
                existing = (await session.execute(
                    select(AppConnectorBinding).where(
                        AppConnectorBinding.app_id == app.id,
                        AppConnectorBinding.alias == binding_spec["alias"],
                    )
                )).scalar_one_or_none()
                if existing:
                    continue
                connector = (await session.execute(
                    select(Connector).where(Connector.name == binding_spec["connector_name"])
                )).scalar_one_or_none()
                if connector is None:
                    continue
                session.add(AppConnectorBinding(
                    app_id=app.id,
                    connector_id=connector.id,
                    alias=binding_spec["alias"],
                    use_latest=True,
                ))
                logger.info("app_connector_binding_seeded",
                            app=app_name, alias=binding_spec["alias"])
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
