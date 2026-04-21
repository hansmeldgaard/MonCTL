"""Ingestion endpoint - receives data from collectors (legacy format)."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_clickhouse, get_db, require_collector_key
from monctl_central.storage.models import AppAssignment, Device
from monctl_common.schemas.metrics import IngestPayload
from monctl_common.utils import utc_now

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest(
    payload: IngestPayload,
    db: AsyncSession = Depends(get_db),
    api_key: dict = Depends(require_collector_key),
):
    """Receive metrics, check results, and events from a collector.

    Returns 202 Accepted after persisting to ClickHouse.
    """
    if api_key["collector_id"] != payload.collector_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Collector ID mismatch",
        )

    ch = get_clickhouse()
    received = utc_now()
    collector_uuid = payload.collector_id

    # Build ClickHouse check result rows
    ch_rows = []
    for app_result in payload.app_results:
        cr = app_result.check_result
        perf = cr.performance_data or {}

        # Enrich from PG (cached)
        enrichment = await _enrich_legacy(db, app_result.assignment_id)

        ch_rows.append({
            "_target_table": enrichment.get("target_table", "availability_latency"),
            "assignment_id": app_result.assignment_id,
            "collector_id": collector_uuid,
            "app_id": app_result.app_id,
            "device_id": enrichment.get("device_id", "00000000-0000-0000-0000-000000000000"),
            "state": cr.state.value,
            "output": cr.output,
            "error_message": "",
            "error_category": cr.error_category,
            "rtt_ms": perf.get("rtt_ms", 0.0) or 0.0,
            "response_time_ms": perf.get("response_time_ms", 0.0) or 0.0,
            "reachable": 1 if perf.get("reachable", 1) else 0,
            "status_code": int(perf.get("status_code", 0) or 0),
            "metric_names": [],
            "metric_values": [],
            "executed_at": app_result.executed_at,
            "execution_time": cr.execution_time or 0.0,
            "device_name": enrichment.get("device_name", ""),
            "app_name": enrichment.get("app_name", ""),
            "role": enrichment.get("role", ""),
            "tenant_id": enrichment.get("tenant_id", "00000000-0000-0000-0000-000000000000"),
        })

    # Build ClickHouse event rows
    event_rows = []
    for event in payload.events:
        event_rows.append({
            "collector_id": collector_uuid,
            "app_id": "00000000-0000-0000-0000-000000000000",
            "source": event.source,
            "severity": event.severity,
            "message": event.message,
            "data": json.dumps(event.data) if event.data else "{}",
            "occurred_at": event.timestamp or received,
        })

    try:
        if ch_rows:
            # Group by target_table
            by_table: dict[str, list[dict]] = {}
            for row in ch_rows:
                tt = row.pop("_target_table", "availability_latency")
                by_table.setdefault(tt, []).append(row)
            for table, rows in by_table.items():
                await asyncio.to_thread(ch.insert_by_table, table, rows)
    except Exception:
        logger.exception("clickhouse_insert_error")

    return {
        "status": "accepted",
        "data": {
            "results_count": len(ch_rows),
            "events_count": len(event_rows),
        },
    }


async def _enrich_legacy(db: AsyncSession, assignment_id: str) -> dict:
    """Resolve denormalized fields for the legacy ingest endpoint."""
    from monctl_central.cache import get_or_load_enrichment
    from monctl_central.storage.models import App
    from sqlalchemy import select

    async def _load(aid: str) -> dict:
        try:
            stmt = (
                select(AppAssignment, App, Device)
                .join(App, AppAssignment.app_id == App.id)
                .outerjoin(Device, AppAssignment.device_id == Device.id)
                .where(AppAssignment.id == uuid.UUID(aid))
            )
            row = (await db.execute(stmt)).first()
            if row is None:
                return {}
            assignment = row.AppAssignment
            app = row.App
            device = row.Device
            return {
                "app_id": str(app.id),
                "app_name": app.name,
                "target_table": app.target_table,
                "device_id": str(device.id) if device else "00000000-0000-0000-0000-000000000000",
                "device_name": device.name if device else "",
                "role": assignment.role or "",
                "tenant_id": str(device.tenant_id) if device and device.tenant_id else "00000000-0000-0000-0000-000000000000",
            }
        except Exception:
            return {}

    return await get_or_load_enrichment(assignment_id, _load)
