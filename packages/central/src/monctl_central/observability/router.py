"""Admin-only readout for the counters helper.

GET /v1/observability/counters?prefix=&days=

Returns a flat ``{name: rolling_total}`` dict. Default window is 1 day
(today UTC); pass ``days=7`` for a weekly view, etc. ``prefix`` filters
to one subsystem family — e.g. ``audit.`` or ``ws.`` — so an operator
debugging one symptom doesn't have to scroll through every counter.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from monctl_central.dependencies import require_admin, require_auth
from monctl_central.observability.counters import all_counters, incr

router = APIRouter()

# Event names follow `<surface>.<verb>` — e.g. `devices_beta.viewed`.
# Whitelist regex keeps random clients from poisoning the counter namespace.
_EVENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}\.[a-z][a-z0-9_]{0,40}$")


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


class UiEventBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: str = Field(min_length=3, max_length=82, description="snake.case event name")


@router.post("/ui-events", status_code=204)
async def post_ui_event(
    body: UiEventBody,
    auth: dict = Depends(require_auth),
):
    """Increment the rolling counter `ui.<event>`.

    Fire-and-forget product-telemetry endpoint for UI surfaces. Used by the
    devices-beta page to track adoption (`ui.devices_beta.viewed`,
    `ui.devices_beta.view_picked`, `ui.devices_beta.view_saved`,
    `ui.devices_beta.bulk_action`, `ui.devices_beta.switched_to_classic`).

    Operators read aggregate counts via
    `GET /v1/observability/counters?prefix=ui.devices_beta&days=7` to decide
    when the redesign is ready to promote (see PR #207 promotion criteria).

    The endpoint deliberately keeps no per-user/per-event row; just the
    rolling counter. Anything richer would need a dedicated table.
    """
    if not _EVENT_NAME_RE.match(body.event):
        raise HTTPException(status_code=422, detail="Invalid event name format")
    await incr(f"ui.{body.event}")
