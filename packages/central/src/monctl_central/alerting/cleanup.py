"""Cleanup resolved AlertEntities past the retention window."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.storage.models import AlertEntity, SystemSetting

logger = logging.getLogger(__name__)


async def cleanup_resolved_instances(session: AsyncSession) -> int:
    """Reset resolved instances past the retention window back to 'ok'.

    Returns the number of instances cleaned up.
    """
    setting = await session.get(SystemSetting, "alert_history_retention_days")
    retention_days = int(setting.value) if setting else 7
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    stmt = (
        update(AlertEntity)
        .where(
            AlertEntity.state == "resolved",
            AlertEntity.last_cleared_at < cutoff,
        )
        .values(
            state="ok",
            last_cleared_at=None,
            started_firing_at=None,
            current_value=None,
            fire_count=0,
            fire_history=[],
        )
    )

    result = await session.execute(stmt)
    count = result.rowcount
    if count > 0:
        logger.info("alert_history_cleanup", cleaned=count, retention_days=retention_days)
    return count
