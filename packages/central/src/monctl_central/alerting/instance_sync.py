"""Auto-create/delete AlertEntities on assignment or definition changes."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.storage.models import (
    AlertEntity,
    AlertDefinition,
    AppAssignment,
    AppVersion,
    ThresholdOverride,
)

logger = logging.getLogger(__name__)


async def _get_latest_version(session: AsyncSession, app_id) -> AppVersion | None:
    return (
        await session.execute(
            select(AppVersion)
            .where(AppVersion.app_id == app_id, AppVersion.is_latest == True)  # noqa: E712
        )
    ).scalar_one_or_none()


async def sync_instances_for_assignment(
    session: AsyncSession,
    assignment: AppAssignment,
) -> None:
    """Create AlertEntities for all definitions on this assignment's app version."""
    version_id = assignment.app_version_id
    if assignment.use_latest:
        latest = await _get_latest_version(session, assignment.app_id)
        if latest:
            version_id = latest.id

    definitions = (
        await session.execute(
            select(AlertDefinition)
            .where(AlertDefinition.app_version_id == version_id)
        )
    ).scalars().all()

    for defn in definitions:
        existing = (
            await session.execute(
                select(AlertEntity)
                .where(
                    AlertEntity.definition_id == defn.id,
                    AlertEntity.assignment_id == assignment.id,
                )
            )
        ).scalar_one_or_none()

        if existing:
            continue

        instance = AlertEntity(
            definition_id=defn.id,
            assignment_id=assignment.id,
            device_id=assignment.device_id,
            enabled=defn.enabled,
            state="ok",
        )
        session.add(instance)


async def sync_instances_for_definition(
    session: AsyncSession,
    definition: AlertDefinition,
) -> None:
    """Create AlertEntities for all existing assignments of this app."""
    assignments = (
        await session.execute(
            select(AppAssignment)
            .where(
                AppAssignment.app_id == definition.app_id,
                AppAssignment.enabled == True,  # noqa: E712
            )
        )
    ).scalars().all()

    for assignment in assignments:
        existing = (
            await session.execute(
                select(AlertEntity)
                .where(
                    AlertEntity.definition_id == definition.id,
                    AlertEntity.assignment_id == assignment.id,
                )
            )
        ).scalar_one_or_none()

        if existing:
            continue

        instance = AlertEntity(
            definition_id=definition.id,
            assignment_id=assignment.id,
            device_id=assignment.device_id,
            enabled=definition.enabled,
            state="ok",
        )
        session.add(instance)


async def migrate_threshold_overrides_by_name(
    session: AsyncSession,
    old_version_id,
    new_version_id,
) -> int:
    """Migrate ThresholdOverrides from old version definitions to new version definitions.

    Matches definitions by name within the same app.
    Returns the number of overrides migrated.
    """
    old_defs = (await session.execute(
        select(AlertDefinition).where(
            AlertDefinition.app_version_id == old_version_id,
        )
    )).scalars().all()
    old_by_name = {d.name: d for d in old_defs}

    new_defs = (await session.execute(
        select(AlertDefinition).where(
            AlertDefinition.app_version_id == new_version_id,
        )
    )).scalars().all()
    new_by_name = {d.name: d for d in new_defs}

    migrated = 0

    for name, old_def in old_by_name.items():
        new_def = new_by_name.get(name)
        if new_def is None:
            continue

        overrides = (await session.execute(
            select(ThresholdOverride).where(
                ThresholdOverride.definition_id == old_def.id,
            )
        )).scalars().all()

        for override in overrides:
            existing = (await session.execute(
                select(ThresholdOverride).where(
                    ThresholdOverride.definition_id == new_def.id,
                    ThresholdOverride.device_id == override.device_id,
                    ThresholdOverride.entity_key == override.entity_key,
                )
            )).scalar_one_or_none()

            if existing is None:
                override.definition_id = new_def.id
                migrated += 1

    return migrated
