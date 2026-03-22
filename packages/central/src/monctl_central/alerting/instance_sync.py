"""Auto-create/delete AlertEntities on assignment or definition changes."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.storage.models import (
    AlertEntity,
    AlertDefinition,
    AppAssignment,
)

logger = logging.getLogger(__name__)


async def sync_instances_for_assignment(
    session: AsyncSession,
    assignment: AppAssignment,
) -> None:
    """Create AlertEntities for all definitions on this assignment's app."""
    definitions = (
        await session.execute(
            select(AlertDefinition)
            .where(AlertDefinition.app_id == assignment.app_id)
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
