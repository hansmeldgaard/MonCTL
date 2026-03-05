"""Ingestion endpoint - receives data from collectors."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.config import settings
from monctl_central.dependencies import get_db, require_collector_key
from monctl_central.storage.models import AppAssignment, CheckResultRecord, Device, EventRecord
from monctl_common.schemas.metrics import IngestPayload
from monctl_common.utils import utc_now

router = APIRouter()


@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest(
    payload: IngestPayload,
    db: AsyncSession = Depends(get_db),
    api_key: dict = Depends(require_collector_key),
):
    """Receive metrics, check results, and events from a collector.

    Returns 202 Accepted after persisting to PostgreSQL.
    """
    # Verify collector_id matches the API key
    if api_key["collector_id"] != payload.collector_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Collector ID mismatch",
        )

    received = utc_now()
    collector_uuid = uuid.UUID(payload.collector_id)

    # Persist check results
    for app_result in payload.app_results:
        cr = app_result.check_result
        record = CheckResultRecord(
            assignment_id=uuid.UUID(app_result.assignment_id),
            collector_id=collector_uuid,
            app_id=uuid.UUID(app_result.app_id),
            state=cr.state.value,
            output=cr.output,
            performance_data=cr.performance_data,
            executed_at=app_result.executed_at,
            received_at=received,
            execution_time=cr.execution_time,
        )
        db.add(record)

    # Persist events
    for event in payload.events:
        event_record = EventRecord(
            collector_id=collector_uuid,
            app_id=None,
            source=event.source,
            severity=event.severity,
            message=event.message,
            data=event.data,
            occurred_at=event.timestamp or received,
            received_at=received,
        )
        db.add(event_record)

    # Collect VictoriaMetrics data points before the session is committed
    vm_points: list[str] = []
    for app_result in payload.app_results:
        perf = app_result.check_result.performance_data or {}
        if "reachable" not in perf and "rtt_ms" not in perf:
            continue

        assignment = await db.get(AppAssignment, uuid.UUID(app_result.assignment_id))
        if assignment is None or assignment.device_id is None:
            continue
        device = await db.get(Device, assignment.device_id)
        if device is None:
            continue

        ts_ms = int(app_result.executed_at.timestamp() * 1000)
        # Sanitize label values to avoid Prometheus line protocol issues
        dev_name = str(device.name).replace('"', '\\"').replace('\n', '')
        labels = (
            f'device_id="{device.id}",'
            f'device_name="{dev_name}",'
            f'role="{assignment.role or ""}",'
            f'app="{app_result.app_id}"'
        )
        if "reachable" in perf:
            vm_points.append(f'monctl_up{{{labels}}} {perf["reachable"]} {ts_ms}')
        if "rtt_ms" in perf and perf["rtt_ms"] is not None:
            vm_points.append(f'monctl_latency_ms{{{labels}}} {perf["rtt_ms"]} {ts_ms}')

    # Fire VictoriaMetrics push in the background — does not block the ingest response
    if vm_points:
        asyncio.create_task(_push_to_victoriametrics("\n".join(vm_points)))

    # Session is auto-committed by get_db() dependency on success
    return {
        "status": "accepted",
        "data": {
            "results_count": len(payload.app_results),
            "events_count": len(payload.events),
        },
    }


async def _push_to_victoriametrics(text: str) -> None:
    """Best-effort push of Prometheus line protocol metrics to VictoriaMetrics."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"{settings.victoriametrics_url}/api/v1/import/prometheus",
                content=text.encode(),
                headers={"Content-Type": "text/plain"},
            )
    except Exception:
        pass  # best-effort — don't fail the ingest response
