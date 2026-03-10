"""Alert notification dispatcher — sends webhook/email notifications."""

from __future__ import annotations

import logging

import httpx

from monctl_central.storage.models import AlertRule

logger = logging.getLogger(__name__)


async def send_notifications(
    rule: AlertRule, assignment_id: str, state: str
) -> None:
    """Send notifications for a firing or resolved alert.

    Iterates over rule.notification_channels and dispatches accordingly.
    Each channel is a dict like:
        {"type": "webhook", "url": "https://...", "secret": "..."}
        {"type": "email", "to": "ops@example.com"}
    """
    for channel in (rule.notification_channels or []):
        try:
            channel_type = channel.get("type", "")
            if channel_type == "webhook":
                await _send_webhook(channel, rule, assignment_id, state)
            elif channel_type == "email":
                logger.info(
                    "email_notification_skipped",
                    reason="email not implemented yet",
                    rule=rule.name,
                    assignment_id=assignment_id,
                )
            else:
                logger.warning("unknown_notification_type", type=channel_type)
        except Exception:
            logger.exception(
                "notification_send_error",
                channel_type=channel.get("type"),
                rule_id=str(rule.id),
            )


async def _send_webhook(
    channel: dict, rule: AlertRule, assignment_id: str, state: str
) -> None:
    """POST alert payload to a webhook URL."""
    url = channel.get("url")
    if not url:
        return

    payload = {
        "alert": {
            "rule_id": str(rule.id),
            "rule_name": rule.name,
            "rule_type": rule.rule_type,
            "severity": rule.severity,
            "state": state,
            "assignment_id": assignment_id,
            "condition": rule.condition,
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
            rule=rule.name,
            state=state,
        )
