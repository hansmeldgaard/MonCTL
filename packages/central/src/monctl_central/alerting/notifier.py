"""Alert notification dispatcher — sends webhook/email notifications."""

from __future__ import annotations

import logging

import httpx

from monctl_central.storage.models import AlertDefinition

logger = logging.getLogger(__name__)


async def send_notifications(
    defn: AlertDefinition, assignment_id: str, state: str
) -> None:
    """Send notifications for a firing or resolved alert.

    Notification channels were removed from alert definitions in the redesign.
    This is now a placeholder for future notification system integration.
    """
    logger.debug(
        "notification_placeholder defn=%s assignment=%s state=%s",
        defn.name, assignment_id, state,
    )


async def _send_webhook(
    channel: dict, defn: AlertDefinition, assignment_id: str, state: str
) -> None:
    """POST alert payload to a webhook URL."""
    url = channel.get("url")
    if not url:
        return

    payload = {
        "alert": {
            "definition_id": str(defn.id),
            "definition_name": defn.name,
            "app_id": str(defn.app_id),
            "severity": defn.severity,
            "state": state,
            "assignment_id": assignment_id,
            "expression": defn.expression,
        }
    }

    headers = {"Content-Type": "application/json"}
    secret = channel.get("secret")
    if secret:
        headers["X-Webhook-Secret"] = secret

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload, headers=headers)
        logger.info(
            "webhook_sent",
            url=url,
            status=resp.status_code,
            definition=defn.name,
            state=state,
        )
