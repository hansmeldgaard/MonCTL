"""Admin-only readout for the counters helper.

GET /v1/observability/counters?prefix=&days=

Returns a flat ``{name: rolling_total}`` dict. Default window is 1 day
(today UTC); pass ``days=7`` for a weekly view, etc. ``prefix`` filters
to one subsystem family — e.g. ``audit.`` or ``ws.`` — so an operator
debugging one symptom doesn't have to scroll through every counter.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from monctl_central.dependencies import require_admin
from monctl_central.observability.counters import all_counters

router = APIRouter()


@router.get("/counters")
async def get_counters(
    prefix: str = Query(default="", max_length=64),
    days: int = Query(default=1, ge=1, le=35),
    auth: dict = Depends(require_admin),
):
    """Return counter rolling sums across the last ``days`` days."""
    totals = await all_counters(days=days, prefix=prefix)
    return {
        "status": "success",
        "data": totals,
        "meta": {"days": days, "prefix": prefix or None, "count": len(totals)},
    }
