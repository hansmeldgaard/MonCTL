"""Collector API — endpoints used by the distributed collector system.

These endpoints replace the old /v1/collectors/{id}/config + /v1/ingest model
with a job-pull model where collectors fetch jobs, app code, and credentials
independently and push results in a collector-native format.

All endpoints are mounted at /api/v1/  (see main.py).
Authentication: Bearer token (API key) in Authorization header — same as existing /v1/.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.credentials.crypto import decrypt_dict
from monctl_central.dependencies import get_clickhouse, get_db, require_collector_auth as require_auth
from sqlalchemy.dialects.postgresql import insert as pg_insert

from monctl_central.storage.models import (
    App,
    AppAssignment,
    AppCache,
    AppConnectorBinding,
    AppVersion,
    AssignmentConnectorBinding,
    AssignmentCredentialOverride,
    Collector,
    Connector,
    ConnectorVersion,
    Credential,
    Device,
    InterfaceMetadata,
)

router = APIRouter()
logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# ACTIVE-status gate for collector endpoints
# ---------------------------------------------------------------------------

async def _require_active_collector(auth: dict, db: AsyncSession) -> None:
    """Raise 403 if the collector is not in ACTIVE status.

    Used by endpoints that should be blocked for PENDING/REJECTED collectors
    (jobs, app metadata/code, credentials).
    """
    collector_id = auth.get("collector_id")
    if not collector_id:
        return  # Non-collector auth (management key, JWT) — skip check

    stmt = select(Collector).where(Collector.id == uuid.UUID(collector_id))
    result = await db.execute(stmt)
    collector = result.scalar_one_or_none()
    if collector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector not found")

    if collector.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Collector is {collector.status} — approval required before accessing this endpoint",
        )


# ---------------------------------------------------------------------------
# Caller-collector resolution + per-collector ownership checks (F-CEN-014/15/16)
# ---------------------------------------------------------------------------

async def _resolve_caller_collector(
    db: AsyncSession,
    auth: dict,
    *,
    fallback_hostname: str | None = None,
    request: Request | None = None,
    hint_collector_id: str | None = None,
) -> Collector | None:
    """Best-effort resolution of the calling collector identity.

    Priority order (strongest first):
      1. `auth["collector_id"]` — present when the caller authenticated via
         their per-collector API key (created at registration). Trusted.
      2. `X-Collector-Id` header (sent by up-to-date collectors on every
         request) or `hint_collector_id` from an explicit query param.
      3. `fallback_hostname` matched against `Collector.hostname` — weaker
         because hostname is caller-supplied in the request body, but it
         matches how the legacy shared-secret flow already identifies the
         caller for denormalisation.

    Returns the Collector row or None when nothing resolves.
    """
    cid = auth.get("collector_id")
    if cid:
        try:
            coll = await db.get(Collector, uuid.UUID(cid))
            if coll is not None:
                return coll
        except ValueError:
            pass

    header_cid = (
        request.headers.get("x-collector-id")
        if request is not None
        else None
    )
    for hint in (hint_collector_id, header_cid):
        if not hint:
            continue
        try:
            coll = await db.get(Collector, uuid.UUID(hint))
            if coll is not None:
                return coll
        except ValueError:
            continue

    if fallback_hostname:
        stmt = select(Collector).where(Collector.hostname == fallback_hostname)
        coll = (await db.execute(stmt)).scalar_one_or_none()
        if coll is not None:
            return coll

    return None


async def _caller_owns_assignment(
    db: AsyncSession, caller: Collector, assignment_id: uuid.UUID,
) -> bool:
    """Return True if `caller` is entitled to submit results / fetch creds / ...
    for the given assignment.

    Entitlement rules:
      - Pinned: `AppAssignment.collector_id == caller.id` → True.
      - Group-level (unpinned): the device must live in the same
        `collector_group_id` the caller belongs to. Any collector in the
        group is trusted to handle any assignment for that group's devices
        (which matches the consistent-hash partitioning — a rebalance can
        re-assign jobs within a group at any time, so pinning a check to
        one specific collector UUID would fight the load balancer).
      - Host-unbound (monitors w/ no device, e.g. central self-checks): the
        assignment may have `device_id IS NULL`. These are treated as
        group-level and allowed for any collector in the pinned group or
        any collector when the assignment itself is unpinned.
    """
    assignment = await db.get(AppAssignment, assignment_id)
    if assignment is None:
        return False

    # Pinned to the caller exactly → always allowed.
    if assignment.collector_id and assignment.collector_id == caller.id:
        return True

    # Pinned to a *different* collector → never allowed.
    if assignment.collector_id and assignment.collector_id != caller.id:
        return False

    # Unpinned assignment — check device/group.
    if assignment.device_id is None:
        # No device → a host-unbound assignment. Accept from any ACTIVE
        # collector; the job scheduler already constrains which collector
        # picks it up via consistent hashing.
        return True

    device = await db.get(Device, assignment.device_id)
    if device is None:
        return False

    if caller.group_id is None or device.collector_group_id is None:
        # Grouping not in use — preserve legacy behaviour, don't block.
        return True

    return device.collector_group_id == caller.group_id


async def _caller_allowed_credentials(
    db: AsyncSession, caller: Collector,
) -> set[str]:
    """Credential names the caller is entitled to fetch.

    Union of three sources (matches the credential-resolution chain):
      1. `AssignmentCredentialOverride` rows for assignments owned by caller.
      2. `AppAssignment.credential_id` for assignments owned by caller.
      3. `Device.credentials` JSONB mapping for devices in caller's group.
    """
    from sqlalchemy.orm import selectinload

    allowed_ids: set[uuid.UUID] = set()

    # Assignments scope: caller-pinned + caller-group unpinned
    owned_assignments_stmt = (
        select(AppAssignment)
        .options(selectinload(AppAssignment.connector_bindings))
        .outerjoin(Device, AppAssignment.device_id == Device.id)
        .where(
            or_(
                AppAssignment.collector_id == caller.id,
                (
                    AppAssignment.collector_id.is_(None)
                    & (
                        Device.collector_group_id == caller.group_id
                        if caller.group_id is not None
                        else True
                    )
                ),
            )
        )
    )
    owned = (await db.execute(owned_assignments_stmt)).scalars().unique().all()
    owned_assignment_ids = [a.id for a in owned]

    for a in owned:
        if a.credential_id:
            allowed_ids.add(a.credential_id)

    # Per-assignment, per-connector-type overrides
    if owned_assignment_ids:
        overrides = (
            await db.execute(
                select(AssignmentCredentialOverride.credential_id).where(
                    AssignmentCredentialOverride.assignment_id.in_(owned_assignment_ids)
                )
            )
        ).scalars().all()
        allowed_ids.update(c for c in overrides if c is not None)

    # Device-level default credentials JSONB — collect every value from any
    # device the caller touches. In the legacy no-group world, this covers
    # devices explicitly pinned via AppAssignment too.
    device_ids: set[uuid.UUID] = set()
    for a in owned:
        if a.device_id:
            device_ids.add(a.device_id)

    if device_ids:
        device_rows = (
            await db.execute(
                select(Device.credentials).where(Device.id.in_(device_ids))
            )
        ).scalars().all()
        for cred_map in device_rows:
            if isinstance(cred_map, dict):
                for v in cred_map.values():
                    if v:
                        try:
                            allowed_ids.add(uuid.UUID(str(v)))
                        except (ValueError, TypeError):
                            continue

    if not allowed_ids:
        return set()

    name_rows = (
        await db.execute(select(Credential.name).where(Credential.id.in_(allowed_ids)))
    ).scalars().all()
    return set(name_rows)


async def _caller_allowed_app_ids(
    db: AsyncSession, caller: Collector,
) -> set[uuid.UUID]:
    """App UUIDs legitimately in use by the caller's owned assignments."""
    if caller.group_id is None:
        # No grouping configured — use every assignment pinned to caller.
        stmt = select(AppAssignment.app_id).where(
            AppAssignment.collector_id == caller.id
        )
    else:
        stmt = (
            select(AppAssignment.app_id)
            .outerjoin(Device, AppAssignment.device_id == Device.id)
            .where(
                or_(
                    AppAssignment.collector_id == caller.id,
                    (
                        AppAssignment.collector_id.is_(None)
                        & (Device.collector_group_id == caller.group_id)
                    ),
                )
            )
        )
    rows = (await db.execute(stmt)).scalars().all()
    return {r for r in rows if r is not None}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _weighted_job_owner(
    assignment_id: str,
    weights: dict[str, float],
    vnodes_base: int = 100,
) -> str:
    """Weighted consistent hashing — returns the hostname that owns this job.

    Each collector gets `vnodes_base * normalized_weight` virtual nodes on a
    SHA256 hash ring. More capacity → more vnodes → more jobs.
    """
    if not weights:
        return ""
    if len(weights) == 1:
        return next(iter(weights))

    # Normalize weights so the max is 1.0
    max_w = max(weights.values()) or 1.0

    # Build ring: list of (hash_value, hostname) sorted by hash_value
    ring_hashes: list[int] = []
    ring_nodes: list[str] = []
    for hostname, w in sorted(weights.items()):
        n_vnodes = max(1, int(vnodes_base * (w / max_w)))
        for i in range(n_vnodes):
            h = int(hashlib.sha256(f"{hostname}:{i}".encode()).hexdigest(), 16)
            idx = bisect.bisect_left(ring_hashes, h)
            ring_hashes.insert(idx, h)
            ring_nodes.insert(idx, hostname)

    # Hash the assignment and find its position on the ring
    key_hash = int(hashlib.sha256(assignment_id.encode()).hexdigest(), 16)
    idx = bisect.bisect_left(ring_hashes, key_hash)
    if idx >= len(ring_hashes):
        idx = 0
    return ring_nodes[idx]


_CRED_REF_RE = re.compile(r"\$credential:([^\"}]+)")


def _extract_credential_names(config: dict) -> list[str]:
    """Return all $credential:<name> references found anywhere in config."""
    raw = json.dumps(config)
    return list({m for m in _CRED_REF_RE.findall(raw)})


def _resolve_credential_refs(
    params: dict,
    device: "Device | None",
    assignment: "AppAssignment",
    cred_name_map: dict,
) -> dict:
    """Replace $credential:<ref> in params with actual credential names.

    The <ref> can be:
      - A credential name directly (e.g. "SSH - monctl") → use as-is
      - __device_default__ → resolve from assignment or device credentials
      - A connector type (e.g. "snmp") → look up in device.credentials JSONB
    """
    cred_names_set = set(cred_name_map.values())
    resolved = {}
    for key, val in params.items():
        if not isinstance(val, str) or not val.startswith("$credential:"):
            resolved[key] = val
            continue
        # Strip one or more $credential: prefixes (some were double-encoded)
        ref = val
        while ref.startswith("$credential:"):
            ref = ref.removeprefix("$credential:")

        # Case 1: ref is already an existing credential name
        if ref in cred_names_set:
            resolved[key] = ref
            continue

        # Case 2: __device_default__ — resolve from assignment or device
        cred_id = None
        if ref == "__device_default__":
            if assignment.credential_id:
                cred_id = assignment.credential_id
            elif device and device.credentials:
                for dev_cred_id in device.credentials.values():
                    try:
                        cred_id = uuid.UUID(str(dev_cred_id))
                        break
                    except (ValueError, TypeError):
                        continue
        else:
            # Case 3: connector type — look up in device credentials JSONB
            if device and device.credentials and ref in device.credentials:
                try:
                    cred_id = uuid.UUID(str(device.credentials[ref]))
                except (ValueError, TypeError):
                    pass
            if not cred_id and assignment.credential_id:
                cred_id = assignment.credential_id

        cred_name = cred_name_map.get(cred_id) if cred_id else None
        if cred_name:
            resolved[key] = cred_name
        else:
            resolved[key] = val
    return resolved


# ---------------------------------------------------------------------------
# GET /api/v1/jobs
# ---------------------------------------------------------------------------

@router.get("/jobs", tags=["collector-api"])
async def get_jobs(
    since: str | None = Query(
        default=None,
        description="ISO-8601 timestamp for delta-sync. Only return jobs updated after this time.",
    ),
    collector_id: str | None = Query(
        default=None,
        description="Collector UUID — filters jobs to only devices in the collector's group.",
    ),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return active jobs (assignments) for a collector.

    If collector_id is provided and the collector belongs to a group,
    only assignments for devices in that group are returned.
    Jobs are partitioned server-side across active collectors in the group
    using consistent hashing so each job is executed by exactly one collector.
    """
    await _require_active_collector(auth, db)

    # Per-collector ownership (F-CEN-014 extension for /jobs). When the caller
    # authenticated with their own API key we trust `auth["collector_id"]` and
    # require the query arg to match — prevents a compromised per-collector
    # key from enumerating another collector's group's assignments by passing
    # a different `collector_id=...`. Shared-secret callers are unchanged.
    if auth.get("auth_type") == "collector_api_key":
        auth_cid = auth.get("collector_id")
        if collector_id is None:
            collector_id = auth_cid
        elif auth_cid and collector_id != auth_cid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="collector_id query does not match authenticated collector",
            )

    since_dt: datetime | None = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid 'since' timestamp: {since!r}. Use ISO-8601 format.",
            )

    # Resolve collector's group for filtering and partitioning
    group_id: uuid.UUID | None = None
    coll: Collector | None = None
    if collector_id:
        try:
            coll = await db.get(Collector, uuid.UUID(collector_id))
        except ValueError:
            coll = None
        if coll and coll.group_id:
            group_id = coll.group_id

    # Fetch enabled assignments with their app, app_version, and device
    from sqlalchemy.orm import selectinload

    _base_opts = (
        selectinload(AppAssignment.connector_bindings),
    )
    _enabled_device_filter = [
        AppAssignment.enabled == True,  # noqa: E712
        or_(
            AppAssignment.device_id.is_(None),
            Device.is_enabled == True,  # noqa: E712
        ),
    ]

    # 1. Fetch assignments pinned to THIS collector (always included, no partitioning)
    pinned_rows = []
    if collector_id:
        pinned_stmt = (
            select(AppAssignment, App, AppVersion, Device)
            .join(App, AppAssignment.app_id == App.id)
            .join(AppVersion, AppAssignment.app_version_id == AppVersion.id)
            .outerjoin(Device, AppAssignment.device_id == Device.id)
            .options(*_base_opts)
            .where(AppAssignment.collector_id == uuid.UUID(collector_id), *_enabled_device_filter)
        )
        if since_dt is not None:
            pinned_stmt = pinned_stmt.where(AppAssignment.updated_at > since_dt)
        pinned_rows = list((await db.execute(pinned_stmt)).all())

    # 2. Fetch unpinned (group-level) assignments for partitioning
    stmt = (
        select(AppAssignment, App, AppVersion, Device)
        .join(App, AppAssignment.app_id == App.id)
        .join(AppVersion, AppAssignment.app_version_id == AppVersion.id)
        .outerjoin(Device, AppAssignment.device_id == Device.id)
        .options(*_base_opts)
        .where(AppAssignment.collector_id.is_(None), *_enabled_device_filter)
    )

    # Filter by collector group: only jobs for devices in this group
    if group_id is not None:
        stmt = stmt.where(Device.collector_group_id == group_id)

    if since_dt is not None:
        stmt = stmt.where(AppAssignment.updated_at > since_dt)

    result = await db.execute(stmt)
    rows = list(result.all())

    # ── Server-side weighted job partitioning ────────────────────────────
    # Partitioning applies ONLY to unpinned (group-level) assignments.
    # Uses a cached weight snapshot on CollectorGroup so the hash ring is
    # stable between rebalancer runs — prevents dual-polling.
    if group_id is not None and coll is not None:
        from monctl_central.storage.models import CollectorGroup

        group_stmt = (
            select(Collector)
            .where(Collector.group_id == group_id, Collector.status == "ACTIVE")
            .order_by(Collector.hostname)  # deterministic ordering
        )
        group_result = await db.execute(group_stmt)
        group_collectors = group_result.scalars().all()

        if len(group_collectors) > 1:
            my_hostname = coll.hostname
            active_hostnames = {c.hostname for c in group_collectors}

            # Use cached weight snapshot if it matches current topology
            group_obj = await db.get(CollectorGroup, group_id)
            snapshot = group_obj.weight_snapshot if group_obj else None
            if snapshot and set(snapshot.keys()) == active_hostnames:
                # Enforce minimum weight to prevent starvation
                weights = {h: max(w, 0.3) for h, w in snapshot.items()}
            else:
                # Topology changed or no snapshot — use equal weights
                weights = {c.hostname: 1.0 for c in group_collectors}

            if my_hostname in weights:
                total_before = len(rows)
                rows = [
                    r for r in rows
                    if _weighted_job_owner(str(r.AppAssignment.id), weights) == my_hostname
                ]
                logger.info(
                    "job_partitioning_weighted",
                    collector=my_hostname,
                    weights=weights,
                    group_size=len(group_collectors),
                    total_jobs=total_before,
                    assigned_jobs=len(rows),
                )

    # Combine: pinned always included + group-level after partitioning
    rows = pinned_rows + rows

    # Pre-load latest versions for apps that have use_latest assignments
    latest_versions: dict[uuid.UUID, AppVersion] = {}
    use_latest_app_ids = {
        row.AppAssignment.app_id for row in rows if row.AppAssignment.use_latest
    }
    if use_latest_app_ids:
        latest_stmt = select(AppVersion).where(
            AppVersion.app_id.in_(use_latest_app_ids),
            AppVersion.is_latest == True,  # noqa: E712
        )
        latest_result = await db.execute(latest_stmt)
        for lv in latest_result.scalars().all():
            latest_versions[lv.app_id] = lv

    # Pre-load monitored interfaces for interface-type jobs (batch query)
    interface_device_ids = {
        row.Device.id for row in rows
        if row.App.target_table == "interface" and row.Device is not None
    }
    monitored_map: dict[str, list[dict]] = {}
    if interface_device_ids:
        iface_stmt = (
            select(InterfaceMetadata)
            .where(
                InterfaceMetadata.device_id.in_(interface_device_ids),
                InterfaceMetadata.polling_enabled == True,  # noqa: E712
            )
            .order_by(InterfaceMetadata.current_if_index)
        )
        iface_result = await db.execute(iface_stmt)
        for meta in iface_result.scalars().all():
            dev_key = str(meta.device_id)
            monitored_map.setdefault(dev_key, []).append({
                "if_index": meta.current_if_index,
                "if_name": meta.if_name,
                "poll_metrics": meta.poll_metrics,
            })

    # Pre-load app-level connector bindings (batch)
    app_ids = {row.App.id for row in rows}
    acb_stmt = select(AppConnectorBinding).where(AppConnectorBinding.app_id.in_(app_ids))
    acb_result = await db.execute(acb_stmt)
    app_bindings_map: dict[uuid.UUID, list[AppConnectorBinding]] = {}
    for acb in acb_result.scalars().all():
        app_bindings_map.setdefault(acb.app_id, []).append(acb)

    # Pre-load assignment credential overrides (batch)
    assignment_ids = {row.AppAssignment.id for row in rows}
    override_stmt = select(AssignmentCredentialOverride).where(
        AssignmentCredentialOverride.assignment_id.in_(assignment_ids)
    )
    override_result = await db.execute(override_stmt)
    overrides_map: dict[uuid.UUID, dict[str, uuid.UUID]] = {}
    for ov in override_result.scalars().all():
        overrides_map.setdefault(ov.assignment_id, {})[ov.connector_type] = ov.credential_id

    # Pre-load latest connector versions for use_latest resolution
    latest_cv_stmt = select(ConnectorVersion).where(ConnectorVersion.is_latest == True)  # noqa: E712
    latest_cv_result = await db.execute(latest_cv_stmt)
    latest_connector_versions: dict[uuid.UUID, uuid.UUID] = {}
    for cv in latest_cv_result.scalars().all():
        latest_connector_versions[cv.connector_id] = cv.id

    # Pre-load connector version checksums for cache invalidation
    all_cv_ids: set[uuid.UUID] = set()
    for row in rows:
        for acb in app_bindings_map.get(row.App.id, []):
            vid = acb.connector_version_id
            if vid is None and acb.connector_id is not None:
                vid = latest_connector_versions.get(acb.connector_id)
            if vid:
                all_cv_ids.add(vid)
        for b in (row.AppAssignment.connector_bindings or []):
            vid = b.connector_version_id
            if vid is None and b.connector_id is not None:
                vid = latest_connector_versions.get(b.connector_id)
            if vid:
                all_cv_ids.add(vid)
    cv_checksum_map: dict[uuid.UUID, str] = {}
    if all_cv_ids:
        cv_stmt = select(ConnectorVersion.id, ConnectorVersion.checksum).where(
            ConnectorVersion.id.in_(all_cv_ids)
        )
        cv_rows = (await db.execute(cv_stmt)).all()
        cv_checksum_map = {r.id: r.checksum or "" for r in cv_rows}

    # Collect all credential IDs we might need names for
    all_cred_ids: set[uuid.UUID] = set()
    for row in rows:
        # Legacy: assignment connector bindings
        for b in (row.AppAssignment.connector_bindings or []):
            if b.credential_id:
                all_cred_ids.add(b.credential_id)
        # Assignment credential_id
        if row.AppAssignment.credential_id:
            all_cred_ids.add(row.AppAssignment.credential_id)
        # Per-protocol credentials from device.credentials JSONB
        if row.Device and row.Device.credentials:
            for cred_val in row.Device.credentials.values():
                try:
                    all_cred_ids.add(uuid.UUID(str(cred_val)))
                except (ValueError, TypeError):
                    pass
    for ov_map in overrides_map.values():
        all_cred_ids.update(ov_map.values())

    cred_name_map: dict[uuid.UUID, str] = {}
    if all_cred_ids:
        cred_stmt = select(Credential.id, Credential.name).where(Credential.id.in_(all_cred_ids))
        cred_rows = (await db.execute(cred_stmt)).all()
        cred_name_map = {r.id: r.name for r in cred_rows}

    jobs = []
    for row in rows:
        assignment: AppAssignment = row.AppAssignment
        app: App = row.App
        app_version: AppVersion = row.AppVersion
        device: Device | None = row.Device

        # Resolve version: use_latest overrides the pinned version
        if assignment.use_latest and assignment.app_id in latest_versions:
            app_version = latest_versions[assignment.app_id]

        # Derive device_host: use device.address if linked, else try config["host"]
        device_host: str | None = None
        if device is not None:
            device_host = device.address
        elif "host" in assignment.config:
            device_host = str(assignment.config["host"])

        # interval in seconds (schedule_type == "interval")
        interval = 60
        if assignment.schedule_type == "interval":
            try:
                interval = int(assignment.schedule_value)
            except ValueError:
                pass

        # max_execution_time from resource_limits
        max_exec = 30
        if assignment.resource_limits and "timeout_seconds" in assignment.resource_limits:
            max_exec = int(assignment.resource_limits["timeout_seconds"])

        # Resolve $credential: references in config to actual credential names
        raw_params = dict(assignment.config)
        params = _resolve_credential_refs(
            raw_params, device, assignment, cred_name_map,
        )
        # Credential names the collector needs to pre-fetch:
        # resolved names (from params) + any still-unresolved refs from config
        credential_names = []
        for key, orig_val in raw_params.items():
            if isinstance(orig_val, str) and orig_val.startswith("$credential:"):
                resolved_val = params.get(key)
                if resolved_val and not str(resolved_val).startswith("$credential:"):
                    credential_names.append(resolved_val)
        if app.target_table == "interface" and device is not None:
            dev_key = str(device.id)
            # Check if a metadata refresh was requested (forces full walk)
            from monctl_central.cache import get_and_clear_interface_refresh_flag
            refresh_requested = await get_and_clear_interface_refresh_flag(dev_key)
            if refresh_requested:
                logger.info("interface_refresh_requested", device_id=dev_key)
                # Omit monitored_interfaces → poller will do a full walk
            elif dev_key in monitored_map:
                params["monitored_interfaces"] = monitored_map[dev_key]

        # Build connector bindings from APP-level bindings (new model)
        # with credential resolution: override > assignment > device default
        app_cbs = app_bindings_map.get(app.id, [])
        cred_overrides = overrides_map.get(assignment.id, {})

        bindings = []
        # Build assignment-level binding overrides keyed by connector_type.
        assign_binding_map: dict[str, "AssignmentConnectorBinding"] = {}
        for b in (assignment.connector_bindings or []):
            assign_binding_map[b.connector_type] = b

        if app_cbs:
            for acb in app_cbs:
                # Skip unfilled / orphaned slots defensively.
                if acb.is_orphaned:
                    continue
                if acb.connector_id is None:
                    logger.warning(
                        "assignment_has_unfilled_slot",
                        assignment_id=str(assignment.id),
                        connector_type=acb.connector_type,
                    )
                    continue

                assign_override = assign_binding_map.get(acb.connector_type)
                effective_connector_id = (
                    assign_override.connector_id if assign_override else acb.connector_id
                )

                # Resolve connector version: assignment override > app binding
                # > latest (when version_id is NULL).
                version_id: uuid.UUID | None = None
                if assign_override and assign_override.connector_version_id:
                    version_id = assign_override.connector_version_id
                elif acb.connector_version_id:
                    version_id = acb.connector_version_id
                else:
                    version_id = latest_connector_versions.get(effective_connector_id)

                # Resolve credential: override > assignment binding >
                # assignment > device.credentials keyed by connector_type.
                cred_id: uuid.UUID | None = None
                if acb.connector_type in cred_overrides:
                    cred_id = cred_overrides[acb.connector_type]
                elif assign_override and assign_override.credential_id:
                    cred_id = assign_override.credential_id
                elif assignment.credential_id:
                    cred_id = assignment.credential_id
                elif (
                    device
                    and device.credentials
                    and acb.connector_type in device.credentials
                ):
                    try:
                        cred_id = uuid.UUID(str(device.credentials[acb.connector_type]))
                    except (ValueError, TypeError):
                        pass

                merged_settings = dict(acb.settings or {})
                if assign_override and assign_override.settings:
                    merged_settings.update(assign_override.settings)

                bindings.append({
                    "connector_type": acb.connector_type,
                    "connector_id": str(effective_connector_id),
                    "connector_version_id": str(version_id) if version_id else None,
                    "credential_name": cred_name_map.get(cred_id) if cred_id else None,
                    "settings": merged_settings,
                    "connector_checksum": cv_checksum_map.get(version_id, "") if version_id else "",
                })
        else:
            # Fallback for apps that pre-date slot sync (no AppConnectorBinding rows).
            for b in (assignment.connector_bindings or []):
                vid = b.connector_version_id
                if vid is None and b.connector_id is not None:
                    vid = latest_connector_versions.get(b.connector_id)
                bindings.append({
                    "connector_type": b.connector_type,
                    "connector_id": str(b.connector_id),
                    "connector_version_id": str(vid) if vid else None,
                    "credential_name": cred_name_map.get(b.credential_id) if b.credential_id else None,
                    "settings": b.settings or {},
                    "connector_checksum": cv_checksum_map.get(vid, "") if vid else "",
                })

        jobs.append({
            "job_id": str(assignment.id),
            "device_id": str(assignment.device_id) if assignment.device_id else None,
            "device_host": device_host,
            "app_id": app.name,
            "app_version": app_version.version,
            "app_checksum": app_version.checksum_sha256 or "",
            "credential_names": credential_names,  # collector fetches each via /credentials/{name}
            "interval": interval,
            "parameters": params,
            "role": assignment.role,
            "max_execution_time": max_exec,
            "enabled": assignment.enabled,
            "updated_at": assignment.updated_at.isoformat() if assignment.updated_at else None,
            "connector_bindings": bindings,
        })

    # ── Inject one-shot SNMP discovery jobs for flagged devices ───────────
    from monctl_central.cache import get_and_clear_discovery_flag

    # Collect device IDs in scope (from jobs + all group devices for new devices)
    discovery_device_ids: set[str] = set()
    for job in jobs:
        if job.get("device_id"):
            discovery_device_ids.add(job["device_id"])

    # Also check devices in collector's group that may not have assignments yet
    if group_id:
        pending_devs = (await db.execute(
            select(Device.id).where(
                Device.collector_group_id == group_id,
                Device.is_enabled == True,  # noqa: E712
            )
        )).scalars().all()
        for dev_id in pending_devs:
            discovery_device_ids.add(str(dev_id))

    # Find snmp_discovery app + latest version
    discovery_app = (await db.execute(
        select(App).where(App.name == "snmp_discovery")
    )).scalar_one_or_none()

    if discovery_app and discovery_device_ids:
        discovery_version = (await db.execute(
            select(AppVersion).where(
                AppVersion.app_id == discovery_app.id,
                AppVersion.is_latest == True,  # noqa: E712
            )
        )).scalar_one_or_none()

        if discovery_version:
            # Get app-level connector bindings for the discovery app
            disc_app_cbs = app_bindings_map.get(discovery_app.id) or []
            if not disc_app_cbs:
                disc_acb_stmt = select(AppConnectorBinding).where(
                    AppConnectorBinding.app_id == discovery_app.id
                )
                disc_app_cbs = list((await db.execute(disc_acb_stmt)).scalars().all())

            flagged_count = 0
            for dev_id_str in discovery_device_ids:
                if not await get_and_clear_discovery_flag(dev_id_str):
                    continue
                flagged_count += 1
                logger.warning("DISCOVERY_FLAG_FOUND", device_id=dev_id_str)

                device = await db.get(Device, uuid.UUID(dev_id_str))
                if not device:
                    logger.warning("discovery_device_not_found_for_flag", device_id=dev_id_str)
                    continue

                # Resolve SNMP credential for discovery
                disc_cred_id: uuid.UUID | None = None
                if device.credentials:
                    for ctype, cval in device.credentials.items():
                        if "snmp" in ctype.lower():
                            try:
                                # credentials JSONB: {type: uuid_str} or {type: {id: uuid_str, ...}}
                                if isinstance(cval, dict):
                                    disc_cred_id = uuid.UUID(str(cval.get("id", "")))
                                else:
                                    disc_cred_id = uuid.UUID(str(cval))
                            except ValueError:
                                pass
                            break
                disc_cred_name = cred_name_map.get(disc_cred_id) if disc_cred_id else None
                # If credential not in our pre-loaded map, look it up
                if disc_cred_id and not disc_cred_name:
                    cred_row = (await db.execute(
                        select(Credential.name).where(Credential.id == disc_cred_id)
                    )).scalar_one_or_none()
                    disc_cred_name = cred_row

                # Build connector bindings for discovery job
                disc_bindings = []
                for acb in disc_app_cbs:
                    if acb.is_orphaned or acb.connector_id is None:
                        continue
                    version_id = acb.connector_version_id
                    if version_id is None:
                        version_id = latest_connector_versions.get(acb.connector_id)
                    disc_bindings.append({
                        "connector_type": acb.connector_type,
                        "connector_id": str(acb.connector_id),
                        "connector_version_id": str(version_id) if version_id else None,
                        "credential_name": disc_cred_name,
                        "settings": acb.settings or {},
                        "connector_checksum": cv_checksum_map.get(version_id, "") if version_id else "",
                    })

                # Collect eligibility OIDs for candidate auto-assign packs
                eligibility_oids_to_probe: list[str] = []
                seen_oids: set[str] = set()

                # Source 1: per-device Redis key from test-eligibility probe mode
                from monctl_central.cache import get_eligibility_oids_for_device
                redis_oids = await get_eligibility_oids_for_device(dev_id_str)
                if redis_oids:
                    for oid_str in redis_oids:
                        if oid_str and oid_str not in seen_oids:
                            seen_oids.add(oid_str)
                            eligibility_oids_to_probe.append(oid_str)

                # Source 2: auto_assign_packs on the device type
                if device.device_type_id:
                    from monctl_central.storage.models import DeviceType as DT, Pack as PackModel
                    dt = await db.get(DT, device.device_type_id)
                    if dt and dt.auto_assign_packs:
                        device_sys_oid = (device.metadata_ or {}).get("sys_object_id")
                        for pack_uid in dt.auto_assign_packs:
                            pack = (await db.execute(
                                select(PackModel).where(PackModel.pack_uid == pack_uid)
                            )).scalar_one_or_none()
                            if not pack:
                                continue
                            pack_apps = (await db.execute(
                                select(App).where(App.pack_id == pack.id)
                            )).scalars().all()
                            for papp in pack_apps:
                                # Vendor scope pre-filter
                                if papp.vendor_oid_prefix and device_sys_oid:
                                    pfx = papp.vendor_oid_prefix
                                    if not (device_sys_oid == pfx or device_sys_oid.startswith(pfx + ".")):
                                        continue
                                latest_v = (await db.execute(
                                    select(AppVersion).where(
                                        AppVersion.app_id == papp.id,
                                        AppVersion.is_latest == True,  # noqa: E712
                                    )
                                )).scalar_one_or_none()
                                if latest_v and latest_v.eligibility_oids:
                                    for ec in latest_v.eligibility_oids:
                                        oid_str = ec.get("oid", "")
                                        if oid_str and oid_str not in seen_oids:
                                            seen_oids.add(oid_str)
                                            eligibility_oids_to_probe.append(oid_str)

                disc_params: dict = {"_one_shot": True}
                if eligibility_oids_to_probe:
                    disc_params["_eligibility_oids"] = eligibility_oids_to_probe

                jobs.append({
                    "job_id": f"discovery-{dev_id_str}",
                    "device_id": dev_id_str,
                    "device_host": device.address,
                    "app_id": discovery_app.name,
                    "app_version": discovery_version.version,
                    "app_checksum": discovery_version.checksum_sha256 or "",
                    "credential_names": [disc_cred_name] if disc_cred_name else [],
                    "interval": 0,  # One-shot: interval=0 signals no reschedule
                    "parameters": disc_params,
                    "role": "discovery",
                    "max_execution_time": 30,
                    "enabled": True,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "connector_bindings": disc_bindings,
                })
                logger.warning("DISCOVERY_JOB_INJECTED", device_id=dev_id_str)

            if flagged_count > 0:
                logger.warning("DISCOVERY_FLAGS_DONE", count=flagged_count)

    return {
        "jobs": jobs,
        "deleted_ids": [],  # soft-delete support: future work
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /api/v1/apps/{app_name}/metadata
# ---------------------------------------------------------------------------

@router.get("/apps/{app_name}/metadata", tags=["collector-api"])
async def get_app_metadata(
    app_name: str,
    version: str | None = Query(default=None, description="Version string. Defaults to latest."),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return app metadata (requirements, entry_class, checksum) for a given app name."""
    await _require_active_collector(auth, db)

    from sqlalchemy.orm import selectinload

    stmt = (
        select(App)
        .options(selectinload(App.versions))
        .where(App.name == app_name)
    )
    result = await db.execute(stmt)
    app = result.scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"App '{app_name}' not found")

    # Pick version: explicit > is_latest > newest
    versions = sorted(app.versions, key=lambda v: v.published_at, reverse=True)
    if version:
        av = next((v for v in versions if v.version == version), None)
        if av is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"App '{app_name}' version '{version}' not found",
            )
    else:
        av = next((v for v in versions if v.is_latest), None) or (versions[0] if versions else None)
        if av is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"App '{app_name}' has no versions",
            )

    return {
        "app_id": app.name,
        "version": av.version,
        "description": app.description,
        "requirements": av.requirements or [],
        "entry_class": av.entry_class or "Poller",
        "checksum": av.checksum_sha256,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/apps/{app_name}/code
# ---------------------------------------------------------------------------

@router.get("/apps/{app_name}/code", tags=["collector-api"])
async def get_app_code(
    app_name: str,
    version: str | None = Query(default=None, description="Version string. Defaults to latest."),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return Python source code for a poll app."""
    await _require_active_collector(auth, db)

    from sqlalchemy.orm import selectinload

    stmt = (
        select(App)
        .options(selectinload(App.versions))
        .where(App.name == app_name)
    )
    result = await db.execute(stmt)
    app = result.scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"App '{app_name}' not found")

    versions = sorted(app.versions, key=lambda v: v.published_at, reverse=True)
    if version:
        av = next((v for v in versions if v.version == version), None)
        if av is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"App '{app_name}' version '{version}' not found",
            )
    else:
        av = next((v for v in versions if v.is_latest), None) or (versions[0] if versions else None)
        if av is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"App '{app_name}' has no versions",
            )

    if not av.source_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"App '{app_name}' v{av.version} has no source code uploaded yet.",
        )

    # Recompute checksum so collectors can verify integrity
    checksum = hashlib.sha256(av.source_code.encode()).hexdigest()

    return {
        "app_id": app.name,
        "version": av.version,
        "code": av.source_code,
        "checksum": checksum,
        "requirements": av.requirements or [],
        "entry_class": av.entry_class or "Poller",
    }


# ---------------------------------------------------------------------------
# PUT /api/v1/apps/{app_name}/code  (upload source code — management op)
# ---------------------------------------------------------------------------

class UploadCodeRequest(BaseModel):
    version: str
    source_code: str
    requirements: list[str] = []
    entry_class: str


@router.put("/apps/{app_name}/code", tags=["collector-api"])
async def upload_app_code(
    app_name: str,
    request: UploadCodeRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Upload Python source code for an app version.

    Creates the app and version if they don't exist yet.
    The checksum is computed server-side from the uploaded source_code.
    """
    from sqlalchemy.orm import selectinload

    stmt = select(App).options(selectinload(App.versions)).where(App.name == app_name)
    result = await db.execute(stmt)
    app = result.scalar_one_or_none()

    if app is None:
        app = App(
            name=app_name,
            description=f"Poll app: {app_name}",
            app_type="poller",
        )
        db.add(app)
        await db.flush()

    # Find or create the version
    av = next((v for v in app.versions if v.version == request.version), None)
    checksum = hashlib.sha256(request.source_code.encode()).hexdigest()

    if av is None:
        av = AppVersion(
            app_id=app.id,
            version=request.version,
            checksum_sha256=checksum,
            source_code=request.source_code,
            requirements=request.requirements,
            entry_class=request.entry_class,
        )
        db.add(av)
    else:
        av.source_code = request.source_code
        av.requirements = request.requirements
        av.entry_class = request.entry_class
        av.checksum_sha256 = checksum

    await db.flush()
    return {
        "app_id": app_name,
        "version": request.version,
        "checksum": checksum,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/credentials/{credential_name}
# ---------------------------------------------------------------------------

@router.get("/credentials/{credential_name}", tags=["collector-api"])
async def get_credential(
    credential_name: str,
    http_request: Request,
    collector_id: str | None = Query(
        default=None,
        description="Caller collector UUID when not authenticated via per-collector key.",
    ),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return decrypted credential data for a named credential.

    Restricted (F-CEN-015) to credentials actually referenced by an
    assignment routed to the caller — prevents full credential vault
    exfiltration via a stolen/misbehaving collector key.
    """
    await _require_active_collector(auth, db)

    caller = await _resolve_caller_collector(
        db, auth,
        request=http_request,
        hint_collector_id=collector_id,
    )

    if caller is not None:
        allowed = await _caller_allowed_credentials(db, caller)
        if credential_name not in allowed:
            logger.warning(
                "collector_credential_unauthorised",
                collector_id=str(caller.id),
                collector_name=caller.name,
                credential_name=credential_name,
            )
            # Deliberate: 404, not 403 — don't leak whether the credential
            # exists at all. Matches the pattern in the auth router.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Credential '{credential_name}' not found",
            )
    else:
        # No caller identity at all — legacy shared-secret without the
        # collector_id query hint. Preserve current behaviour but log so
        # ops can see which deployments still need the per-collector key.
        logger.warning(
            "collector_credential_no_identity",
            credential_name=credential_name,
            auth_type=auth.get("auth_type"),
        )

    stmt = select(Credential).where(Credential.name == credential_name)
    result = await db.execute(stmt)
    cred = result.scalar_one_or_none()
    if cred is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential '{credential_name}' not found",
        )

    try:
        data = decrypt_dict(cred.secret_data)
    except Exception as exc:
        logger.error("credential_decrypt_error", name=credential_name, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt credential",
        ) from exc

    return {
        "name": cred.name,
        "type": cred.credential_type,
        "data": data,
    }


# ---------------------------------------------------------------------------
# POST /api/v1/results
# ---------------------------------------------------------------------------

class CollectorResult(BaseModel):
    job_id: str                       # = assignment_id UUID
    device_id: str | None = None
    timestamp: float                  # Unix timestamp
    metrics: list[dict] = []
    config_data: dict | None = None   # Key-value config/inventory data for config-table apps
    status: str = "ok"               # "ok" | "warning" | "critical" | "unknown" | "error"
    reachable: bool = True
    error_message: str | None = None
    error_category: str = ""          # "device", "config", "app", or ""
    execution_time_ms: int | None = None
    rtt_ms: float | None = None
    response_time_ms: float | None = None
    started_at: float | None = None
    interface_rows: list[dict] | None = None  # Per-interface data for interface-table apps


class SubmitResultsRequest(BaseModel):
    collector_node: str               # hostname of the cache-node
    results: list[CollectorResult]
    # Deterministic per-batch id supplied by the collector (F-COL-038). When
    # present, central short-circuits duplicate POSTs caused by in-flight
    # response loss with a 202 no-op instead of re-ingesting. Older
    # collectors that predate the forwarder bump will omit this and simply
    # keep the prior at-least-once behaviour.
    batch_id: str | None = None


# TTL for the "batch already ingested" marker. A minute is plenty — mid-
# flight response loss is measured in seconds. Longer than the forwarder's
# max backoff (300s) so a retry at peak backoff still hits the marker.
_BATCH_DEDUP_TTL = 900


_STATUS_TO_STATE = {
    "ok": 0,
    "warning": 1,
    "critical": 2,
    "unknown": 3,
    "error": 2,
}


def _calculate_rate(
    current_octets: int,
    previous_octets: int,
    dt_seconds: float,
    if_speed_mbps: int = 0,
) -> tuple[float, bool]:
    """Calculate rate in bps from counter delta.

    Returns (rate_bps, is_valid).
    current < previous = always reset (no wrap detection).
    Rejects rates > 110% of link speed as implausible.
    """
    if dt_seconds <= 0:
        return 0.0, False
    if current_octets < previous_octets:
        return 0.0, False
    if current_octets == previous_octets:
        return 0.0, True

    delta = current_octets - previous_octets
    rate_bps = (delta * 8) / dt_seconds

    # Reject implausible rates
    max_rate = (if_speed_mbps * 1_000_000 * 1.1) if if_speed_mbps > 0 else 110_000_000_000
    if rate_bps > max_rate:
        return 0.0, False

    return rate_bps, True


def _calculate_utilization(rate_bps: float, if_speed_mbps: int) -> float:
    """Returns utilization percentage, capped at 100%."""
    if if_speed_mbps <= 0 or rate_bps <= 0:
        return 0.0
    pct = (rate_bps / (if_speed_mbps * 1_000_000)) * 100
    return min(pct, 100.0)


# ── Performance counter normalization ────────────────────────

_PERF_PREV_PREFIX = "perf-prev:"
_PERF_PREV_TTL = 1200  # 20 minutes


def _calculate_perf_rate(
    current_value: float,
    previous_value: float,
    dt_seconds: float,
) -> float:
    """Calculate rate (per second) from counter delta.

    current < previous = always reset (no wrap detection).
    """
    if dt_seconds <= 0:
        return 0.0
    if current_value < previous_value:
        return 0.0
    if current_value == previous_value:
        return 0.0
    return (current_value - previous_value) / dt_seconds


async def _get_previous_perf_counters(
    device_id: str, component_type: str, component: str,
) -> dict | None:
    """Get previous counter values for a performance component.

    Returns dict like {"read_bytes": {"value": 123, "executed_at": "..."}, ...}
    Falls back to ClickHouse performance_latest if Redis cache expired.
    """
    from monctl_central.cache import _redis

    cache_key = f"{_PERF_PREV_PREFIX}{device_id}:{component_type}:{component}"

    if _redis:
        try:
            cached = await _redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    # Fallback: ClickHouse performance_latest
    try:
        import asyncio
        from monctl_central.dependencies import get_clickhouse
        ch = get_clickhouse()
        if ch:
            rows = await asyncio.to_thread(
                ch._get_client().query,
                "SELECT metric_names, metric_values, metric_types, executed_at "
                "FROM performance_latest FINAL "
                "WHERE device_id = {device_id:UUID} "
                "  AND component_type = {component_type:String} "
                "  AND component = {component:String} "
                "LIMIT 1",
                parameters={
                    "device_id": device_id,
                    "component_type": component_type,
                    "component": component,
                },
            )
            named = list(rows.named_results())
            if named:
                row = named[0]
                names = row.get("metric_names", [])
                values = row.get("metric_values", [])
                types = row.get("metric_types", [])
                ea = row["executed_at"]
                ea_iso = ea.isoformat() if hasattr(ea, "isoformat") else str(ea)

                prev: dict = {}
                for i, name in enumerate(names):
                    mt = types[i] if i < len(types) else "gauge"
                    if mt == "counter":
                        prev[name] = {
                            "value": values[i] if i < len(values) else 0,
                            "executed_at": ea_iso,
                        }
                if prev:
                    if _redis:
                        await _redis.set(cache_key, json.dumps(prev), ex=_PERF_PREV_TTL)
                    return prev
    except Exception:
        pass

    return None


async def _cache_perf_counters(
    device_id: str, component_type: str, component: str,
    counter_data: dict, executed_at_iso: str,
) -> None:
    """Cache current counter values. ALWAYS called — even on reset."""
    from monctl_central.cache import _redis
    if not _redis:
        return
    cache_key = f"{_PERF_PREV_PREFIX}{device_id}:{component_type}:{component}"
    cache = {
        name: {"value": val, "executed_at": executed_at_iso}
        for name, val in counter_data.items()
    }
    if cache:
        try:
            await _redis.set(cache_key, json.dumps(cache), ex=_PERF_PREV_TTL)
        except Exception:
            pass


async def _resolve_interface_id(
    db: AsyncSession,
    device_id: str,
    if_name: str,
    if_index: int,
    if_descr: str = "",
    if_alias: str = "",
    if_speed_mbps: int = 0,
) -> tuple[str, bool]:
    """Resolve or create stable interface_id from (device_id, if_name).

    Redis cached (1h). Auto-creates InterfaceMetadata on first discovery.
    Detects if_index changes and updates accordingly.

    Returns (interface_id, polling_enabled).
    """
    from monctl_central.cache import get_cached_interface_id, set_cached_interface_id

    # 1. Check Redis cache
    cached = await get_cached_interface_id(device_id, if_name)
    if cached:
        cached_id = cached["interface_id"]
        cached_if_index = cached.get("current_if_index")
        polling_enabled = cached.get("polling_enabled", True)
        if cached_if_index == if_index:
            return cached_id, polling_enabled
        # if_index changed — update PG and cache
        try:
            meta = await db.get(InterfaceMetadata, uuid.UUID(cached_id))
            if meta:
                metadata_changed = False
                meta.current_if_index = if_index
                if if_descr and if_descr != meta.if_descr:
                    meta.if_descr = if_descr
                    metadata_changed = True
                if if_alias and if_alias != meta.if_alias:
                    meta.if_alias = if_alias
                    metadata_changed = True
                if if_speed_mbps and if_speed_mbps != meta.if_speed_mbps:
                    meta.if_speed_mbps = if_speed_mbps
                    metadata_changed = True
                from monctl_common.utils import utc_now
                meta.updated_at = utc_now()
                await db.flush()

                # Re-evaluate interface rules if metadata changed and rules_managed
                if metadata_changed and meta.rules_managed:
                    try:
                        device = await db.get(Device, uuid.UUID(device_id))
                        if device and device.interface_rules:
                            from monctl_central.templates.interface_rules import apply_rules_to_interface
                            if apply_rules_to_interface(meta, device.interface_rules, force=True):
                                await db.flush()
                    except Exception:
                        logger.debug("Failed to re-evaluate interface rules", exc_info=True)

                polling_enabled = meta.polling_enabled
                logger.info(
                    "if_index_changed",
                    device_id=device_id,
                    if_name=if_name,
                    old_if_index=cached_if_index,
                    new_if_index=if_index,
                )
            cache_data = {
                "interface_id": cached_id,
                "current_if_index": if_index,
                "polling_enabled": polling_enabled,
            }
            await set_cached_interface_id(device_id, if_name, cache_data)
        except Exception:
            logger.debug("Failed to update if_index change", exc_info=True)
        return cached_id, polling_enabled

    # 2. PG lookup by (device_id, if_name)
    stmt = select(InterfaceMetadata).where(
        InterfaceMetadata.device_id == uuid.UUID(device_id),
        InterfaceMetadata.if_name == if_name,
    )
    result = await db.execute(stmt)
    meta = result.scalar_one_or_none()

    if meta is not None:
        # Update if_index if changed
        if meta.current_if_index != if_index:
            meta.current_if_index = if_index
            from monctl_common.utils import utc_now
            meta.updated_at = utc_now()
            await db.flush()
        interface_id = str(meta.id)
        polling_enabled = meta.polling_enabled
        cache_data = {
            "interface_id": interface_id,
            "current_if_index": if_index,
            "polling_enabled": polling_enabled,
        }
        await set_cached_interface_id(device_id, if_name, cache_data)
        return interface_id, polling_enabled

    # 3. Create new InterfaceMetadata (new interfaces default to polling_enabled=True)
    new_meta = InterfaceMetadata(
        device_id=uuid.UUID(device_id),
        if_name=if_name,
        current_if_index=if_index,
        if_descr=if_descr,
        if_alias=if_alias,
        if_speed_mbps=if_speed_mbps,
    )
    db.add(new_meta)
    await db.flush()

    # Apply interface rules from device (if any)
    polling_enabled = new_meta.polling_enabled
    try:
        device = await db.get(Device, uuid.UUID(device_id))
        if device and device.interface_rules:
            from monctl_central.templates.interface_rules import apply_rules_to_interface
            if apply_rules_to_interface(new_meta, device.interface_rules, force=True):
                await db.flush()
                polling_enabled = new_meta.polling_enabled
    except Exception:
        logger.debug("Failed to apply interface rules on new interface", exc_info=True)

    interface_id = str(new_meta.id)
    cache_data = {
        "interface_id": interface_id,
        "current_if_index": if_index,
        "polling_enabled": polling_enabled,
    }
    await set_cached_interface_id(device_id, if_name, cache_data)
    return interface_id, polling_enabled


@router.post("/results", status_code=status.HTTP_202_ACCEPTED, tags=["collector-api"])
async def submit_results(
    request: SubmitResultsRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Receive monitoring results from a collector node.

    Results are inserted into ClickHouse for time-series storage.
    Denormalized fields (device_name, app_name, role, tenant_id) are resolved
    from PostgreSQL and cached in Redis.
    """
    ch = get_clickhouse()

    # Idempotency: collectors stamp a deterministic batch_id so a retry of
    # the same rows (triggered by an in-flight response drop) short-circuits
    # here instead of re-ingesting into ClickHouse. Best-effort: if Redis is
    # down we fall through to the ingest path — duplicates are preferable to
    # dropping a batch entirely. (F-COL-038)
    if request.batch_id:
        from monctl_central.cache import _redis
        if _redis is not None:
            try:
                marker = f"batch_seen:{request.batch_id}"
                if await _redis.get(marker):
                    logger.info(
                        "collector_results_batch_duplicate",
                        batch_id=request.batch_id,
                        collector_node=request.collector_node,
                        results=len(request.results),
                    )
                    return {
                        "status": "success",
                        "data": {
                            "duplicate": True,
                            "ingested": 0,
                            "skipped": 0,
                            "unauthorised": 0,
                        },
                    }
            except Exception as exc:
                logger.debug("batch_dedup_check_failed", error=str(exc))

    # Resolve the caller's collector identity so we can enforce per-collector
    # ownership on assignment IDs the caller claims results for (F-CEN-014).
    # Prefers the per-collector API-key path; falls back to hostname match,
    # which is what the denorm logic below already relies on.
    caller_collector = await _resolve_caller_collector(
        db, auth,
        fallback_hostname=request.collector_node,
        request=http_request,
    )
    collector_uuid = (
        str(caller_collector.id) if caller_collector
        else "00000000-0000-0000-0000-000000000000"
    )
    if caller_collector is None:
        # No identity at all — can't enforce. Log loudly so ops notice any
        # collector still running unbranded; accept results to preserve the
        # pre-fix behaviour until the fleet is fully migrated.
        logger.warning(
            "collector_results_no_identity",
            collector_node=request.collector_node,
            auth_type=auth.get("auth_type"),
        )

    ch_rows = []
    skipped = 0
    unauthorised = 0
    for r in request.results:
        # Handle discovery jobs (job_id = "discovery-{device_id}", not a UUID)
        is_discovery = r.job_id.startswith("discovery-")
        if is_discovery:
            device_id_str = r.job_id.removeprefix("discovery-")
            try:
                device_id_resolved = str(uuid.UUID(device_id_str))
            except ValueError:
                skipped += 1
                continue
            if r.config_data:
                try:
                    from monctl_central.discovery.service import process_discovery_result
                    await process_discovery_result(
                        device_id=device_id_resolved,
                        config_data=r.config_data,
                        db=db,
                    )
                    logger.info("discovery_result_processed", device_id=device_id_resolved)
                except Exception as _disc_exc:
                    logger.warning("discovery_processing_failed",
                                   device_id=device_id_resolved, error=str(_disc_exc))
            continue

        try:
            assignment_id = uuid.UUID(r.job_id)
        except ValueError:
            skipped += 1
            continue

        # Per-assignment ownership check (F-CEN-014). Only enforced when we
        # have a resolved caller collector — otherwise we'd lock out any
        # legacy shared-secret caller. Every rejection is logged so a
        # misbehaving or compromised collector shows up in audit logs.
        if caller_collector is not None:
            owns = await _caller_owns_assignment(db, caller_collector, assignment_id)
            if not owns:
                logger.warning(
                    "collector_results_unauthorised",
                    collector_id=str(caller_collector.id),
                    collector_name=caller_collector.name,
                    assignment_id=str(assignment_id),
                )
                unauthorised += 1
                continue

        # Map status string to integer state
        state = _STATUS_TO_STATE.get(r.status.lower(), 3)
        if not r.reachable and state == 0:
            state = 2

        # Build output string
        if r.error_message:
            output = r.error_message
        elif r.reachable:
            rtt = r.rtt_ms or r.response_time_ms
            output = f"OK — {rtt:.1f}ms" if rtt else "OK"
        else:
            output = "CRITICAL — unreachable"

        executed_at = datetime.fromtimestamp(r.timestamp, tz=timezone.utc)

        # Resolve denormalized fields via cache
        enrichment = await _enrich_assignment(db, str(assignment_id))

        # Extract metric arrays from the metrics list
        metric_names = []
        metric_values = []
        for m in (r.metrics or []):
            if isinstance(m, dict) and "name" in m and "value" in m:
                metric_names.append(str(m["name"]))
                metric_values.append(float(m["value"]))

        target_table = enrichment.get("target_table", "availability_latency")
        device_id_resolved = r.device_id or enrichment.get("device_id", "00000000-0000-0000-0000-000000000000")
        started_at_dt = datetime.fromtimestamp(r.started_at, tz=timezone.utc) if r.started_at else executed_at

        # Performance-table apps: metrics may have component/component_type grouping
        # Each unique (component, component_type) becomes a separate ClickHouse row
        if target_table == "performance" and r.metrics:
            # Group metrics by (component, component_type)
            component_groups: dict[tuple[str, str], tuple[list[str], list[float], list[str]]] = {}
            for m in r.metrics:
                if not isinstance(m, dict):
                    continue
                comp = m.get("component", "")
                comp_type = m.get("component_type", "")
                key = (comp, comp_type)
                if key not in component_groups:
                    component_groups[key] = ([], [], [])
                raw_types = m.get("metric_types", [])
                for idx, (mn, mv) in enumerate(zip(m.get("metric_names", []), m.get("metric_values", []))):
                    component_groups[key][0].append(str(mn))
                    component_groups[key][1].append(float(mv))
                    component_groups[key][2].append(raw_types[idx] if idx < len(raw_types) else "gauge")
                # Also support flat name/value metrics (no metric_names array)
                if "name" in m and "value" in m and "metric_names" not in m:
                    component_groups[key][0].append(str(m["name"]))
                    component_groups[key][1].append(float(m["value"]))
                    component_groups[key][2].append("gauge")

            if component_groups:
                for (comp, comp_type), (mnames, mvalues, mtypes) in component_groups.items():
                    # Normalize counter metrics to rates
                    normalized_values = list(mvalues)
                    has_counters = any(t == "counter" for t in mtypes)
                    if has_counters:
                        previous = await _get_previous_perf_counters(
                            device_id_resolved, comp_type, comp,
                        )
                        counter_data: dict[str, float] = {}
                        for i, (name, value, mtype) in enumerate(zip(mnames, mvalues, mtypes)):
                            if mtype == "counter":
                                counter_data[name] = value
                                if previous and name in previous:
                                    try:
                                        prev_entry = previous[name]
                                        prev_ts_str = prev_entry["executed_at"]
                                        if isinstance(prev_ts_str, str):
                                            if prev_ts_str.endswith("Z"):
                                                prev_ts_str = prev_ts_str[:-1] + "+00:00"
                                            prev_ts = datetime.fromisoformat(prev_ts_str)
                                            if prev_ts.tzinfo is None:
                                                prev_ts = prev_ts.replace(tzinfo=timezone.utc)
                                        else:
                                            prev_ts = prev_ts_str
                                        dt = (executed_at - prev_ts).total_seconds()
                                        normalized_values[i] = _calculate_perf_rate(
                                            value, prev_entry["value"], dt,
                                        )
                                    except (ValueError, TypeError, KeyError):
                                        normalized_values[i] = 0.0
                                else:
                                    normalized_values[i] = 0.0
                        await _cache_perf_counters(
                            device_id_resolved, comp_type, comp,
                            counter_data, executed_at.isoformat(),
                        )

                    ch_rows.append({
                        "_target_table": "performance",
                        "assignment_id": str(assignment_id),
                        "collector_id": collector_uuid,
                        "app_id": enrichment.get("app_id", str(assignment_id)),
                        "device_id": device_id_resolved,
                        "component": comp,
                        "component_type": comp_type,
                        "state": state,
                        "output": "",
                        "error_message": r.error_message or "",
                        "error_category": r.error_category,
                        "metric_names": mnames,
                        "metric_values": normalized_values,
                        "metric_types": mtypes,
                        "executed_at": executed_at,
                        "execution_time": (r.execution_time_ms / 1000.0) if r.execution_time_ms else 0.0,
                        "started_at": started_at_dt,
                        "collector_name": request.collector_node,
                        "device_name": enrichment.get("device_name", ""),
                        "app_name": enrichment.get("app_name", ""),
                        "tenant_id": enrichment.get("tenant_id", "00000000-0000-0000-0000-000000000000"),
                        "tenant_name": enrichment.get("tenant_name", ""),
                    })
                continue  # Skip the default row builder below

        # Interface-table apps: if no interface_rows (e.g. SNMP timeout), skip
        # this result entirely. Interface poller failures should NOT be written
        # to availability_latency — they pollute the availability/latency chart.
        # The device's dedicated availability check already tracks reachability.
        if target_table == "interface" and not r.interface_rows:
            skipped += 1
            continue

        if target_table == "interface" and r.interface_rows:
            from monctl_central.cache import (
                get_previous_counters_batch,
                cache_current_counters_batch,
            )

            # Phase A: Resolve all interface_ids (PG lookups — still sequential)
            resolved_interfaces: list[dict] = []
            for iface in r.interface_rows:
                iface_name = iface.get("if_name", "")
                iface_index = iface.get("if_index", 0)
                iface_alias = iface.get("if_alias", "")
                iface_speed = iface.get("if_speed_mbps", 0)

                interface_id, polling_enabled = await _resolve_interface_id(
                    db, device_id_resolved, iface_name, iface_index,
                    if_descr="", if_alias=iface_alias, if_speed_mbps=iface_speed,
                )
                if not polling_enabled:
                    continue
                resolved_interfaces.append({
                    **iface,
                    "interface_id": interface_id,
                    "if_speed_mbps": iface_speed,
                })

            if not resolved_interfaces:
                skipped += 1
                continue

            # Phase B: Batch-fetch all previous counters (1 Redis pipeline)
            iface_ids = [ri["interface_id"] for ri in resolved_interfaces]
            prev_map = await get_previous_counters_batch(iface_ids)

            # Phase C: Calculate rates and build CH rows
            cache_entries: list[dict] = []
            for ri in resolved_interfaces:
                iid = ri["interface_id"]
                in_octets = ri.get("in_octets", 0)
                out_octets = ri.get("out_octets", 0)
                if_speed = ri["if_speed_mbps"]

                in_rate = 0.0
                out_rate = 0.0
                in_util = 0.0
                out_util = 0.0
                prev = prev_map.get(iid)
                if prev:
                    try:
                        prev_ts_str = prev["executed_at"]
                        if isinstance(prev_ts_str, str):
                            if prev_ts_str.endswith("Z"):
                                prev_ts_str = prev_ts_str[:-1] + "+00:00"
                            prev_ts = datetime.fromisoformat(prev_ts_str)
                            if prev_ts.tzinfo is None:
                                prev_ts = prev_ts.replace(tzinfo=timezone.utc)
                        else:
                            prev_ts = prev_ts_str
                        dt_sec = (executed_at - prev_ts).total_seconds()
                        in_rate, _ = _calculate_rate(in_octets, prev["in_octets"], dt_sec, if_speed)
                        out_rate, _ = _calculate_rate(out_octets, prev["out_octets"], dt_sec, if_speed)
                        in_util = _calculate_utilization(in_rate, if_speed)
                        out_util = _calculate_utilization(out_rate, if_speed)
                    except (ValueError, TypeError):
                        pass

                cache_entries.append({
                    "interface_id": iid,
                    "in_octets": in_octets,
                    "out_octets": out_octets,
                    "executed_at_iso": executed_at.isoformat(),
                })

                ch_rows.append({
                    "_target_table": "interface",
                    "assignment_id": str(assignment_id),
                    "collector_id": collector_uuid,
                    "app_id": enrichment.get("app_id", str(assignment_id)),
                    "device_id": device_id_resolved,
                    "interface_id": iid,
                    "if_index": ri.get("if_index", 0),
                    "if_name": ri.get("if_name", ""),
                    "if_alias": ri.get("if_alias", ""),
                    "if_speed_mbps": if_speed,
                    "if_admin_status": ri.get("if_admin_status", ""),
                    "if_oper_status": ri.get("if_oper_status", ""),
                    "in_octets": in_octets,
                    "out_octets": out_octets,
                    "in_errors": ri.get("in_errors", 0),
                    "out_errors": ri.get("out_errors", 0),
                    "in_discards": ri.get("in_discards", 0),
                    "out_discards": ri.get("out_discards", 0),
                    "in_unicast_pkts": ri.get("in_unicast_pkts", 0),
                    "out_unicast_pkts": ri.get("out_unicast_pkts", 0),
                    "in_rate_bps": in_rate,
                    "out_rate_bps": out_rate,
                    "in_utilization_pct": in_util,
                    "out_utilization_pct": out_util,
                    "poll_interval_sec": ri.get("poll_interval_sec", 0),
                    "counter_bits": ri.get("counter_bits", 64),
                    "state": ri.get("state", 0),
                    "execution_time": (r.execution_time_ms / 1000.0) if r.execution_time_ms else 0.0,
                    "executed_at": executed_at,
                    "collector_name": request.collector_node,
                    "device_name": enrichment.get("device_name", ""),
                    "app_name": enrichment.get("app_name", ""),
                    "tenant_id": enrichment.get("tenant_id", "00000000-0000-0000-0000-000000000000"),
                    "tenant_name": enrichment.get("tenant_name", ""),
                })

            # Phase D: Batch-cache all current counters (1 Redis pipeline)
            await cache_current_counters_batch(cache_entries)
        elif target_table == "config" and r.config_data:
            # Config-table apps: each key-value pair becomes a separate ClickHouse row
            import hashlib as _hashlib
            _base = {
                "assignment_id": str(assignment_id),
                "collector_id": collector_uuid,
                "app_id": enrichment.get("app_id", str(assignment_id)),
                "device_id": device_id_resolved,
                "component": "",
                "component_type": enrichment.get("app_name", ""),
                "state": state,
                # Surface error/output on every per-key row — the /by-device
                # "latest" lookup keys on (device, component_type, component,
                # config_key), so any row can be what the UI sees. Repeating
                # the assignment-level error fields keeps the signal intact.
                "output": output,
                "error_message": r.error_message or "",
                "error_category": r.error_category,
                "reachable": 1 if r.reachable else 0,
                "execution_time": (r.execution_time_ms / 1000.0) if r.execution_time_ms else 0.0,
                "executed_at": executed_at,
                "collector_name": request.collector_node,
                "device_name": enrichment.get("device_name", ""),
                "app_name": enrichment.get("app_name", ""),
                "tenant_id": enrichment.get("tenant_id", "00000000-0000-0000-0000-000000000000"),
                "tenant_name": enrichment.get("tenant_name", ""),
            }
            _config_rows = []
            for cfg_key, cfg_value in r.config_data.items():
                val_str = str(cfg_value) if cfg_value is not None else ""
                _config_rows.append({
                    **_base,
                    "_target_table": "config",
                    "config_key": cfg_key,
                    "config_value": val_str,
                    "config_hash": _hashlib.md5(val_str.encode()).hexdigest(),
                })
            ch_rows.extend(_config_rows)

            # Process discovery results if this is the snmp_discovery app
            if enrichment.get("app_name") == "snmp_discovery" and r.config_data and device_id_resolved:
                try:
                    from monctl_central.discovery.service import process_discovery_result
                    await process_discovery_result(
                        device_id=device_id_resolved,
                        config_data=r.config_data,
                        db=db,
                    )
                except Exception as _disc_exc:
                    logger.warning("discovery_processing_failed",
                                   device_id=device_id_resolved, error=str(_disc_exc))
        else:
            # Extract packet_loss_pct from metrics (emitted by ping_check)
            loss_pct = 0.0
            for m in (r.metrics or []):
                if isinstance(m, dict) and m.get("name") == "packet_loss_pct":
                    try:
                        loss_pct = float(m.get("value", 0))
                    except (TypeError, ValueError):
                        pass
                    break

            row = {
                "_target_table": target_table,
                "assignment_id": str(assignment_id),
                "collector_id": collector_uuid,
                "app_id": enrichment.get("app_id", str(assignment_id)),
                "device_id": device_id_resolved,
                "state": state,
                "output": output,
                "error_message": r.error_message or "",
                "error_category": r.error_category,
                "rtt_ms": r.rtt_ms or 0.0,
                "response_time_ms": r.response_time_ms or 0.0,
                "reachable": 1 if r.reachable else 0,
                "packet_loss_pct": loss_pct,
                "status_code": 0,
                "metric_names": metric_names,
                "metric_values": metric_values,
                "executed_at": executed_at,
                "execution_time": (r.execution_time_ms / 1000.0) if r.execution_time_ms else 0.0,
                "started_at": started_at_dt,
                "collector_name": request.collector_node,
                "device_name": enrichment.get("device_name", ""),
                "app_name": enrichment.get("app_name", ""),
                "role": enrichment.get("role", ""),
                "tenant_id": enrichment.get("tenant_id", "00000000-0000-0000-0000-000000000000"),
                "tenant_name": enrichment.get("tenant_name", ""),
            }
            # Table-specific required fields
            if target_table == "performance":
                row["component"] = ""
                row["component_type"] = ""
            elif target_table == "config":
                # Error case for a config-target app: single sentinel row.
                # output / error_message / error_category / reachable are
                # already set on `row` above — no need to hijack config_value
                # as the error carrier anymore (now that config has proper
                # error columns).
                row["component"] = ""
                row["component_type"] = enrichment.get("app_name", "")
                row["config_key"] = ""
                row["config_value"] = ""
                row["config_hash"] = ""
            ch_rows.append(row)

    # Route results to the correct ClickHouse table via write buffer
    if ch_rows:
        by_table: dict[str, list[dict]] = {}
        for row in ch_rows:
            tt = row.pop("_target_table", "availability_latency")
            by_table.setdefault(tt, []).append(row)

        from monctl_central.storage.ch_buffer import get_ch_buffer
        buf = get_ch_buffer()
        for table, rows in by_table.items():
            if buf is not None:
                await buf.append(table, rows)
            else:
                try:
                    ch.insert_by_table(table, rows)
                except Exception:
                    logger.exception("clickhouse_insert_error", node=request.collector_node, table=table)

    # Stamp the dedup marker only after the ingest path ran without raising.
    # If central crashed mid-ingest the marker is absent, so the collector's
    # retry will re-ingest as expected. Marker TTL covers the forwarder's
    # max backoff window.
    if request.batch_id:
        from monctl_central.cache import _redis
        if _redis is not None:
            try:
                await _redis.set(
                    f"batch_seen:{request.batch_id}", "1", ex=_BATCH_DEDUP_TTL,
                )
            except Exception as exc:
                logger.debug("batch_dedup_mark_failed", error=str(exc))

    return {
        "accepted": len(ch_rows),
        "skipped": skipped,
        "unauthorised": unauthorised,
    }


# ---------------------------------------------------------------------------
async def _enrich_assignment(db: AsyncSession, assignment_id: str) -> dict:
    """Resolve denormalized fields for a given assignment_id, with Redis caching."""
    from monctl_central.cache import get_or_load_enrichment

    async def _load(aid: str) -> dict:
        try:
            from monctl_central.storage.models import Tenant

            stmt = (
                select(AppAssignment, App, Device, Tenant)
                .join(App, AppAssignment.app_id == App.id)
                .outerjoin(Device, AppAssignment.device_id == Device.id)
                .outerjoin(Tenant, Device.tenant_id == Tenant.id)
                .where(AppAssignment.id == uuid.UUID(aid))
            )
            row = (await db.execute(stmt)).first()
            if row is None:
                return {}
            assignment, app, device, tenant = row.AppAssignment, row.App, row.Device, row.Tenant
            return {
                "app_id": str(app.id),
                "app_name": app.name,
                "target_table": app.target_table,
                "device_id": str(device.id) if device else "00000000-0000-0000-0000-000000000000",
                "device_name": device.name if device else "",
                "role": assignment.role or "",
                "tenant_id": str(device.tenant_id) if device and device.tenant_id else "00000000-0000-0000-0000-000000000000",
                "tenant_name": tenant.name if tenant else "",
            }
        except Exception:
            return {}

    return await get_or_load_enrichment(assignment_id, _load)


# ---------------------------------------------------------------------------
# POST /api/v1/heartbeat
# ---------------------------------------------------------------------------

class HeartbeatRequest(BaseModel):
    node_id: str                # hostname or unique node identifier
    load_score: float = 0.0    # sum(avg_time/interval) for active jobs
    worker_count: int = 0
    effective_load: float = 0.0
    deadline_miss_rate: float = 0.0
    total_jobs: int = 0
    container_states: dict[str, str] | None = None
    queue_stats: dict | None = None
    job_costs: dict[str, float] | None = None  # {assignment_id: avg_execution_time_seconds}
    system_resources: dict | None = None  # cpu_load, cpu_count, memory_total_mb, memory_used_mb, disk_*
    system_stats: dict | None = None  # monctl_version, os_info


@router.post("/heartbeat", tags=["collector-api"])
async def collector_heartbeat(
    request: HeartbeatRequest,
    raw_request: Request,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Receive heartbeat from a cache-node.

    Updates last_seen_at on the matching Collector record (matched by hostname).
    If no matching Collector record exists, the heartbeat is acknowledged but not stored
    (in the new design, collectors are not pre-registered).
    """
    from monctl_common.utils import utc_now

    stmt = select(Collector).where(Collector.hostname == request.node_id)
    result = await db.execute(stmt)
    collector = result.scalar_one_or_none()

    if collector is not None:
        collector.last_seen_at = utc_now()
        # Don't flip PENDING or REJECTED to ACTIVE via heartbeat
        if collector.status not in ("PENDING", "REJECTED"):
            collector.status = "ACTIVE"
        states = dict(collector.reported_peer_states or {})
        if request.container_states:
            states["_container_states"] = request.container_states
        if request.queue_stats:
            states["_queue_stats"] = request.queue_stats
        if request.system_resources:
            states["_system_resources"] = request.system_resources
        collector.reported_peer_states = states
        # Persist load metrics for weighted job partitioning
        collector.load_score = request.load_score
        collector.effective_load = request.effective_load
        collector.total_jobs = request.total_jobs
        collector.worker_count = request.worker_count
        collector.deadline_miss_rate = request.deadline_miss_rate
        collector.load_updated_at = utc_now()

        # Stamp Collector.ip_addresses with the real host IP (from X-Forwarded-For
        # via HAProxy). Docker bridge IPs are not useful for matching to
        # SystemVersion entries, which use the real host IP.
        real_ip = raw_request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if real_ip:
            existing_ips = collector.ip_addresses or []
            if isinstance(existing_ips, dict):
                existing_ips = list(existing_ips.values())
            if not isinstance(existing_ips, list):
                existing_ips = []
            if real_ip not in existing_ips:
                existing_ips = [real_ip] + [ip for ip in existing_ips if ip != real_ip]
                collector.ip_addresses = existing_ips

        await db.flush()

        # Persist per-assignment execution times for cost-aware rebalancing
        if request.job_costs:
            from monctl_central.storage.models import AppAssignment

            for aid_str, avg_time in request.job_costs.items():
                try:
                    aid = uuid.UUID(aid_str)
                except ValueError:
                    continue
                await db.execute(
                    update(AppAssignment)
                    .where(AppAssignment.id == aid)
                    .values(avg_execution_time=avg_time)
                )
            await db.flush()

    # Update SystemVersion for this collector (if an entry exists).
    # SystemVersion entries for collectors are created by the sidecar inventory
    # system using real host IPs. The heartbeat only updates existing entries
    # with OS/version info — it does NOT create new ones (to avoid duplicates
    # when the container hostname differs from the host-level hostname).
    if collector is not None and request.system_stats:
        from monctl_central.storage.models import SystemVersion

        # Match by hostname first, then fall back to IP resolution
        sv = (await db.execute(
            select(SystemVersion).where(SystemVersion.node_hostname == collector.hostname)
        )).scalars().first()

        # If not found by hostname, try matching via real IP (X-Forwarded-For)
        if not sv:
            real_ip = raw_request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            if real_ip:
                sv = (await db.execute(
                    select(SystemVersion).where(
                        SystemVersion.node_ip == real_ip,
                        SystemVersion.node_role == "collector",
                    )
                )).scalars().first()

        if sv:
            os_info = request.system_stats.get("os_info") or {}
            sv.monctl_version = request.system_stats.get("monctl_version") or sv.monctl_version
            sv.os_version = os_info.get("os_version") or sv.os_version
            sv.kernel_version = os_info.get("kernel_version") or sv.kernel_version
            sv.python_version = os_info.get("python_version") or sv.python_version
            if "reboot_required" in request.system_stats:
                sv.reboot_required = request.system_stats["reboot_required"]
            sv.last_reported_at = utc_now()
            await db.flush()

    return {
        "ok": True,
        "node_id": request.node_id,
        "known": collector is not None,
    }


# ---------------------------------------------------------------------------
# PEP 503 Simple Repository API — serves wheels to collectors
# ---------------------------------------------------------------------------

@router.get("/pypi/simple/", tags=["collector-api"])
async def pypi_simple_index(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """PEP 503 simple index — list all approved packages as HTML links."""
    from fastapi.responses import HTMLResponse
    from monctl_central.storage.models import PythonModule

    stmt = (
        select(PythonModule)
        .where(PythonModule.is_approved == True)  # noqa: E712
        .order_by(PythonModule.name)
    )
    result = await db.execute(stmt)
    modules = result.scalars().all()

    links = []
    for m in modules:
        links.append(f'<a href="/api/v1/pypi/simple/{m.name}/">{m.name}</a>')

    html = (
        "<!DOCTYPE html>\n<html><head><title>Simple Index</title></head>\n"
        "<body>\n" + "\n".join(links) + "\n</body></html>"
    )
    return HTMLResponse(content=html, media_type="text/html")


@router.get("/pypi/simple/{package_name}/", tags=["collector-api"])
async def pypi_simple_package(
    package_name: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """PEP 503 package page — list wheel files with sha256 hashes."""
    from fastapi.responses import HTMLResponse
    from monctl_central.storage.models import PythonModule, PythonModuleVersion, WheelFile
    from monctl_central.python_modules.wheel_parser import normalize_package_name

    normalized = normalize_package_name(package_name)
    stmt = select(PythonModule).where(PythonModule.name == normalized)
    result = await db.execute(stmt)
    module = result.scalar_one_or_none()
    if not module:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Package not found")

    # Fetch all wheel files for this module
    wheel_stmt = (
        select(WheelFile)
        .join(PythonModuleVersion, WheelFile.module_version_id == PythonModuleVersion.id)
        .where(PythonModuleVersion.module_id == module.id)
        .order_by(WheelFile.filename)
    )
    wheel_result = await db.execute(wheel_stmt)
    wheels = wheel_result.scalars().all()

    links = []
    for w in wheels:
        links.append(
            f'<a href="/api/v1/pypi/wheels/{w.filename}#sha256={w.sha256_hash}">'
            f'{w.filename}</a>'
        )

    html = (
        f"<!DOCTYPE html>\n<html><head><title>Links for {normalized}</title></head>\n"
        f"<body>\n<h1>Links for {normalized}</h1>\n"
        + "\n".join(links)
        + "\n</body></html>"
    )
    return HTMLResponse(content=html, media_type="text/html")


@router.get("/pypi/wheels/{filename}", tags=["collector-api"])
async def pypi_serve_wheel(
    filename: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Serve a wheel file — first from disk, falling back to database."""
    from fastapi.responses import FileResponse, Response
    from monctl_central.config import settings
    from monctl_central.python_modules.wheel_parser import normalize_package_name, parse_wheel_filename
    from monctl_central.storage.models import WheelFile

    try:
        parts = parse_wheel_filename(filename)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid wheel filename",
        )

    # Try disk first
    normalized = normalize_package_name(parts["name"])
    wheel_path = Path(settings.wheel_storage_dir) / normalized / filename
    if wheel_path.exists():
        return FileResponse(
            path=str(wheel_path),
            media_type="application/octet-stream",
            filename=filename,
        )

    # Fall back to database blob (shared across all nodes)
    stmt = select(WheelFile).where(WheelFile.filename == filename)
    wf = (await db.execute(stmt)).scalar_one_or_none()
    if wf is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wheel file '{filename}' not found. The required python module may need "
                   f"to be imported first via the Modules page.",
        )
    if not wf.file_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wheel file '{filename}' is registered but has no stored data. "
                   f"Delete and re-import the module to fix this.",
        )

    # Cache to disk for future requests
    wheel_path.parent.mkdir(parents=True, exist_ok=True)
    wheel_path.write_bytes(wf.file_data)

    return Response(
        content=wf.file_data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Connector endpoints for collectors
# ---------------------------------------------------------------------------

@router.get("/connectors/{connector_id}/metadata", tags=["collector-api"])
async def get_connector_metadata(
    connector_id: str,
    version_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return connector metadata (name, version, requirements, entry_class, checksum).

    By default returns the latest version. If version_id is provided, returns that
    specific version.
    """
    connector = await db.get(Connector, uuid.UUID(connector_id))
    if connector is None:
        raise HTTPException(status_code=404, detail="Connector not found")

    if version_id:
        stmt = select(ConnectorVersion).where(
            ConnectorVersion.id == uuid.UUID(version_id),
            ConnectorVersion.connector_id == connector.id,
        )
    else:
        stmt = select(ConnectorVersion).where(
            ConnectorVersion.connector_id == connector.id,
            ConnectorVersion.is_latest == True,  # noqa: E712
        )

    version = (await db.execute(stmt)).scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Connector version not found")

    return {
        "name": connector.name,
        "connector_type": connector.connector_type,
        "version": version.version,
        "version_id": str(version.id),
        "requirements": version.requirements,
        "entry_class": version.entry_class,
        "checksum": version.checksum,
    }


@router.get("/connectors/{connector_id}/code", tags=["collector-api"])
async def get_connector_code(
    connector_id: str,
    version_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return the source code for a connector version.

    If version_id is provided, returns that specific version's code.
    Otherwise returns the latest version's code.
    """
    connector = await db.get(Connector, uuid.UUID(connector_id))
    if connector is None:
        raise HTTPException(status_code=404, detail="Connector not found")

    if version_id:
        stmt = select(ConnectorVersion).where(
            ConnectorVersion.id == uuid.UUID(version_id),
            ConnectorVersion.connector_id == connector.id,
        )
    else:
        stmt = select(ConnectorVersion).where(
            ConnectorVersion.connector_id == connector.id,
            ConnectorVersion.is_latest == True,  # noqa: E712
        )

    version = (await db.execute(stmt)).scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Connector version not found")

    return {
        "connector_id": str(connector.id),
        "version_id": str(version.id),
        "version": version.version,
        "entry_class": version.entry_class,
        "checksum": version.checksum,
        "source_code": version.source_code,
    }


# ---------------------------------------------------------------------------
# POST /api/v1/app-cache/push
# ---------------------------------------------------------------------------

class AppCachePushEntry(BaseModel):
    app_id: str
    device_id: str
    cache_key: str
    cache_value: dict
    ttl_seconds: int | None = None
    updated_at: str


class AppCachePushRequest(BaseModel):
    entries: list[AppCachePushEntry]


async def _resolve_collector_group(
    db: AsyncSession, auth: dict, collector_id_param: str | None, node_id_param: str | None,
) -> uuid.UUID:
    """Resolve the collector's group_id from auth, collector_id param, or node_id param."""
    # Try auth dict first (individual API key)
    cid = auth.get("collector_id")
    if not cid and collector_id_param:
        cid = collector_id_param
    if cid:
        collector = await db.get(Collector, uuid.UUID(cid))
        if collector and collector.group_id:
            return collector.group_id
    # Fallback: look up by hostname
    if node_id_param:
        stmt = select(Collector).where(Collector.hostname == node_id_param)
        collector = (await db.execute(stmt)).scalar_one_or_none()
        if collector and collector.group_id:
            return collector.group_id
    raise HTTPException(status_code=400, detail="Cannot resolve collector group")


@router.post("/app-cache/push", tags=["collector-api"])
async def push_app_cache(
    req: AppCachePushRequest,
    http_request: Request,
    collector_id: str | None = Query(None),
    node_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Collectors push dirty cache entries to central.

    Cache writes are scoped to the caller's `collector_group_id`, and
    entries for `app_id` values the caller isn't actually running are
    rejected (F-CEN-016) — prevents a misbehaving collector from
    poisoning cache rows for unrelated apps within its group.
    """
    group_id = await _resolve_collector_group(db, auth, collector_id, node_id)

    # Per-app ownership gate (F-CEN-016). Only enforced when we can resolve
    # a caller identity; otherwise preserves the legacy behaviour.
    caller = await _resolve_caller_collector(
        db, auth,
        request=http_request,
        hint_collector_id=collector_id,
    )

    allowed_app_ids: set[uuid.UUID] | None = None
    if caller is not None:
        allowed_app_ids = await _caller_allowed_app_ids(db, caller)

    # Resolve app names → UUIDs (collectors use app name, DB uses UUID)
    app_names = {e.app_id for e in req.entries}
    app_name_to_id: dict[str, uuid.UUID] = {}
    if app_names:
        stmt = select(App.id, App.name).where(App.name.in_(app_names))
        rows = (await db.execute(stmt)).all()
        app_name_to_id = {r.name: r.id for r in rows}

    accepted = 0
    rejected = 0
    unauthorised = 0

    for entry in req.entries:
        try:
            entry_updated_at = datetime.fromisoformat(entry.updated_at)
        except (ValueError, TypeError):
            rejected += 1
            continue

        # Resolve app_id: try as name first, then as UUID
        resolved_app_id = app_name_to_id.get(entry.app_id)
        if resolved_app_id is None:
            try:
                resolved_app_id = uuid.UUID(entry.app_id)
            except ValueError:
                logger.warning("app_cache_push_unknown_app", app_id=entry.app_id)
                rejected += 1
                continue

        if allowed_app_ids is not None and resolved_app_id not in allowed_app_ids:
            logger.warning(
                "app_cache_push_unauthorised",
                collector_id=str(caller.id) if caller else None,
                app_id=str(resolved_app_id),
            )
            unauthorised += 1
            continue

        try:
            resolved_device_id = uuid.UUID(entry.device_id)
        except ValueError:
            rejected += 1
            continue

        ins = pg_insert(AppCache).values(
            collector_group_id=group_id,
            app_id=resolved_app_id,
            device_id=resolved_device_id,
            cache_key=entry.cache_key,
            cache_value=entry.cache_value,
            ttl_seconds=entry.ttl_seconds,
            updated_at=entry_updated_at,
        )
        upsert = ins.on_conflict_do_update(
            constraint="uq_app_cache_entry",
            set_={
                "cache_value": ins.excluded.cache_value,
                "ttl_seconds": ins.excluded.ttl_seconds,
                "updated_at": ins.excluded.updated_at,
            },
            where=AppCache.updated_at < ins.excluded.updated_at,
        )
        await db.execute(upsert)
        accepted += 1

    await db.flush()
    return {
        "status": "success",
        "data": {
            "accepted": accepted,
            "rejected": rejected,
            "unauthorised": unauthorised,
        },
    }


# ---------------------------------------------------------------------------
# GET /api/v1/app-cache/pull
# ---------------------------------------------------------------------------

@router.get("/app-cache/pull", tags=["collector-api"])
async def pull_app_cache(
    since: str | None = Query(None),
    limit: int = Query(1000, le=5000),
    collector_id: str | None = Query(None),
    node_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Collectors pull cache entries updated since their last sync."""
    group_id = await _resolve_collector_group(db, auth, collector_id, node_id)

    stmt = (
        select(AppCache)
        .where(AppCache.collector_group_id == group_id)
        .order_by(AppCache.updated_at.asc())
        .limit(limit + 1)
    )

    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid 'since' timestamp")
        stmt = stmt.where(AppCache.updated_at > since_dt)

    rows = (await db.execute(stmt)).scalars().all()

    # Resolve app UUIDs → names (collectors use app name as key)
    app_ids = {row.app_id for row in rows}
    app_id_to_name: dict[uuid.UUID, str] = {}
    if app_ids:
        name_rows = (await db.execute(
            select(App.id, App.name).where(App.id.in_(app_ids))
        )).all()
        app_id_to_name = {r.id: r.name for r in name_rows}

    now = datetime.now(timezone.utc)
    entries = []
    for row in rows[:limit]:
        # Skip expired entries
        if row.ttl_seconds is not None:
            if row.updated_at.timestamp() + row.ttl_seconds < now.timestamp():
                continue
        # Use app name (not UUID) so collectors can match their local cache keys
        app_name = app_id_to_name.get(row.app_id)
        if app_name is None:
            continue  # Skip entries for deleted apps
        entries.append({
            "app_id": app_name,
            "device_id": str(row.device_id),
            "cache_key": row.cache_key,
            "cache_value": row.cache_value,
            "ttl_seconds": row.ttl_seconds,
            "updated_at": row.updated_at.isoformat(),
        })

    has_more = len(rows) > limit
    return {"status": "success", "data": {"entries": entries, "has_more": has_more}}


from monctl_central.upgrades.collector_api import router as upgrade_collector_router
router.include_router(upgrade_collector_router, prefix="/upgrade", tags=["upgrade"])

from monctl_central.upgrades.os_collector_api import router as os_packages_router
router.include_router(os_packages_router, prefix="/os-packages", tags=["os-packages"])

from monctl_central.logs.router import router as logs_collector_router
router.include_router(logs_collector_router, tags=["logs"])
