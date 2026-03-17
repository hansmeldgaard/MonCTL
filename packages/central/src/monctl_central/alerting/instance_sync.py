"""Auto-create/delete AlertInstances on assignment or definition changes."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.storage.models import (
    AlertInstance,
    AppAlertDefinition,
    AppAssignment,
    AppVersion,
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
    """Create AlertInstances for all definitions on this assignment's app version."""
    version_id = assignment.app_version_id
    if assignment.use_latest:
        latest = await _get_latest_version(session, assignment.app_id)
        if latest:
            version_id = latest.id

    definitions = (
        await session.execute(
            select(AppAlertDefinition)
            .where(AppAlertDefinition.app_version_id == version_id)
        )
    ).scalars().all()

    for defn in definitions:
        existing = (
            await session.execute(
                select(AlertInstance)
                .where(
                    AlertInstance.definition_id == defn.id,
                    AlertInstance.assignment_id == assignment.id,
                )
            )
        ).scalar_one_or_none()

        if existing:
            continue

        instance = AlertInstance(
            definition_id=defn.id,
            assignment_id=assignment.id,
            device_id=assignment.device_id,
            enabled=defn.enabled,
            state="ok",
        )
        session.add(instance)


async def sync_instances_for_definition(
    session: AsyncSession,
    definition: AppAlertDefinition,
) -> None:
    """Create AlertInstances for all existing assignments of this app."""
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
                select(AlertInstance)
                .where(
                    AlertInstance.definition_id == definition.id,
                    AlertInstance.assignment_id == assignment.id,
                )
            )
        ).scalar_one_or_none()

        if existing:
            continue

        instance = AlertInstance(
            definition_id=definition.id,
            assignment_id=assignment.id,
            device_id=assignment.device_id,
            enabled=definition.enabled,
            state="ok",
        )
        session.add(instance)
