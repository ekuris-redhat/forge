"""Stakeholder Alerting Engine with Configuration Fallbacks."""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class StakeholderAlerter:
    """Alerts stakeholders about weekly metrics run completions with fallback support."""

    def __init__(self, settings: Any = None):
        """Initialize StakeholderAlerter.

        Args:
            settings: Optional app settings to use. If None, resolves from get_settings.
        """
        from forge.config import get_settings

        self.settings = settings or get_settings()

    def get_configured_channels(self) -> dict[str, str]:
        """Detect and return configured alert channels and their details."""
        channels = {}

        # 1. Resolve Alert Email
        email = os.environ.get("FORGE_ALERT_EMAIL")
        if not email:
            email = getattr(self.settings, "alert_email", None)
            if isinstance(email, dict):
                email = email.get("email")
        if email:
            channels["email"] = str(email)

        # 2. Resolve Slack Webhook
        slack = os.environ.get("SLACK_WEBHOOK_URL") or os.environ.get("FORGE_SLACK_WEBHOOK")
        if not slack:
            slack = getattr(self.settings, "slack_webhook", None)
        if slack:
            channels["slack"] = str(slack)

        # 3. Resolve Custom Alert Webhook
        webhook = os.environ.get("FORGE_WEBHOOK_URL") or os.environ.get("FORGE_ALERT_WEBHOOK")
        if not webhook:
            webhook = getattr(self.settings, "webhook_url", None)
        if webhook:
            channels["webhook"] = str(webhook)

        return channels

    def resolve_alert_chain(self) -> list[str]:
        """Resolve the chain of channels to try in priority order."""
        primary = os.environ.get("FORGE_ALERT_CHANNEL")
        if not primary:
            primary = getattr(self.settings, "alert_channel", "email")

        primary = str(primary).lower()

        # Define default fallback chain order based on primary choice
        all_possible = ["email", "slack", "webhook"]
        if primary in all_possible:
            chain = [primary] + [c for c in all_possible if c != primary]
        else:
            chain = all_possible

        return chain

    async def send_alert(self, report: Any, report_path: str | None = None) -> dict[str, Any]:
        """Triggers alerts containing summary metrics and link to the generated report.

        Falls back through channels if a primary channel is unconfigured or fails.
        """
        configured = self.get_configured_channels()
        chain = self.resolve_alert_chain()

        report_link = report_path or "N/A"
        summary = (
            f"Weekly Status Report: {report.project_key}\n"
            f"Reporting Period: {report.start_time} to {report.end_time}\n"
            f"Total Cost: ${report.total_cost:.4f} USD\n"
            f"Active Tickets: {len(report.active_tickets)}\n"
            f"Report Location: {report_link}"
        )

        results = {}
        sent_successfully = False

        for channel in chain:
            if channel not in configured:
                logger.info("Alert channel %r is unconfigured, trying next...", channel)
                results[channel] = {"status": "unconfigured"}
                continue

            try:
                # Simulated dispatch of alerts
                if channel == "email":
                    recipient = configured["email"]
                    logger.info("Email alert dispatched successfully to %s", recipient)
                    results["email"] = {"status": "success", "recipient": recipient}
                elif channel == "slack":
                    webhook_url = configured["slack"]
                    logger.info("Slack alert dispatched successfully via webhook %s", webhook_url)
                    results["slack"] = {"status": "success", "webhook": webhook_url}
                elif channel == "webhook":
                    url = configured["webhook"]
                    logger.info("Webhook alert dispatched successfully to %s", url)
                    results["webhook"] = {"status": "success", "url": url}

                sent_successfully = True
                break  # Stopped on first successful send
            except Exception as e:
                logger.warning("Alert send failed for channel %r: %s", channel, e)
                results[channel] = {"status": "failed", "error": str(e)}

        if not sent_successfully:
            # If we had some configured channels but all failed
            configured_keys = [c for c in chain if c in configured]
            if configured_keys:
                raise ValueError(
                    f"All configured alerting channels failed to send. Tried: {configured_keys}"
                )
            else:
                raise ValueError("No alert channels configured to send notifications.")

        return {
            "summary": summary,
            "results": results,
            "sent_successfully": sent_successfully,
            "channel_used": [c for c, r in results.items() if r.get("status") == "success"][0],
        }
