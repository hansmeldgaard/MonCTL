"""Alert notification dispatcher — sends webhook/email notifications."""

from __future__ import annotations

import logging

import httpx

from monctl_central.storage.models import AppAlertDefinition

logger = logging.getLogger(__name__)


async def send_notifications(
    defn: AppAlertDefinition, assignment_id: str, state: str
) -> None:
    """Send notifications for a firing or resolved alert.

    Iterates over defn.notification_channels and dispatches accordingly.
    Each channel is a dict like:
        {"type": "webhook", "url": "https://...", "secret": "..."}
        {"type": "email", "to": "ops@example.com"}
    """
    for channel in (defn.notification_channels or []):
        try:
            channel_type = channel.get("type", "")
            if channel_type == "webhook":
                await _send_webhook(channel, defn, assignment_id, state)
            elif channel_type == "email":
                logger.info(
                    "email_notification_skipped",
                    reason="email not implemented yet",
                    definition=defn.name,
                    assignment_id=assignment_id,
                )
            else:
                logger.warning("unknown_notification_type", type=channel_type)
        except Exception:
            logger.exception(
                "notification_send_error",
                channel_type=channel.get("type"),
                definition_id=str(defn.id),
            )


async def _send_webhook(
    channel: dict, defn: AppAlertDefinition, assignment_id: str, state: str
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
