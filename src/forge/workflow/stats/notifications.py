"""Jira-native notification delivery for weekly report generation.

This module provides functions to notify project stakeholders when a weekly
report is generated, using Jira's native notification mechanisms (comments
with user mentions).

Usage::

    from forge.workflow.stats.notifications import (
        get_notification_recipients,
        notify_report_ready,
    )

    recipients = await get_notification_recipients("PROJ")
    await notify_report_ready("PROJ-42", recipients)

Configuration:
    - ``FORGE_WEEKLY_REPORT_NOTIFY`` env var: comma-separated Jira account IDs
      (e.g. ``"abc123,def456"``) or the special value ``"project-leads"`` to
      read recipients from the project property ``forge.weekly-report.notify``.
    - Jira project property ``forge.weekly-report.notify``: list of Jira
      account IDs (JSON array or comma-separated string) that overrides the
      global env var for a specific project.

Priority: project property > env var.
"""

from __future__ import annotations

import logging
from typing import Any

from forge.config import get_settings
from forge.integrations.jira.client import JiraClient

logger = logging.getLogger(__name__)

#: Jira project property key for per-project notification recipients.
_NOTIFY_PROPERTY_KEY = "forge.weekly-report.notify"

#: Special sentinel value meaning "read recipients from the project property".
_PROJECT_LEADS_SENTINEL = "project-leads"


def _format_mention(account_id: str) -> str:
    """Format a Jira account ID as a mention string.

    Uses Jira's ``[~accountid:{id}]`` mention syntax so that the user receives
    a Jira notification when the comment is posted.

    Args:
        account_id: Jira account ID (e.g. ``"5e7e3b1a..."``)

    Returns:
        Mention string in the form ``"[~accountid:5e7e3b1a...]"``.
    """
    return f"[~accountid:{account_id}]"


def _parse_account_ids(raw: Any) -> list[str]:
    """Parse a list of Jira account IDs from various raw formats.

    Accepts:
    - A JSON array of strings (from a Jira project property)
    - A comma-separated string (from an env var or a string property)
    - A plain string (single account ID)

    Empty strings and whitespace-only entries are filtered out.

    Args:
        raw: Raw value — a list, a comma-separated string, or any other value.

    Returns:
        Deduplicated list of non-empty account ID strings, preserving order.
    """
    if isinstance(raw, list):
        ids = [str(item).strip() for item in raw if str(item).strip()]
    elif isinstance(raw, str):
        ids = [part.strip() for part in raw.split(",") if part.strip()]
    else:
        return []

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for aid in ids:
        if aid not in seen:
            seen.add(aid)
            unique.append(aid)
    return unique


async def _get_project_property_recipients(project: str) -> list[str] | None:
    """Fetch the ``forge.weekly-report.notify`` project property.

    Args:
        project: Jira project key (e.g. ``"PROJ"``).

    Returns:
        Parsed list of account IDs, or ``None`` if the property is not set or
        cannot be read.
    """
    jira = JiraClient()
    try:
        value = await jira.get_project_property(project, _NOTIFY_PROPERTY_KEY)
    except Exception as exc:
        logger.warning(
            "Failed to read project property %r for project %r: %s",
            _NOTIFY_PROPERTY_KEY,
            project,
            exc,
        )
        return None
    finally:
        await jira.close()

    if value is None:
        return None

    ids = _parse_account_ids(value)
    return ids if ids else None


async def get_notification_recipients(project: str) -> list[str]:
    """Retrieve the list of Jira account IDs to notify for a weekly report.

    Resolution order (highest priority first):

    1. **Per-project Jira property** ``forge.weekly-report.notify`` — if set,
       its value is used unconditionally (overrides the env var).
    2. **Env var** ``FORGE_WEEKLY_REPORT_NOTIFY`` — comma-separated account IDs
       or the special value ``"project-leads"`` which triggers a lookup of the
       project property instead of being treated as a literal account ID.
    3. Empty list — no notifications are sent.

    Args:
        project: Jira project key (e.g. ``"PROJ"``).

    Returns:
        List of Jira account IDs.  May be empty if no recipients are configured.
    """
    # 1. Check per-project property first
    project_ids = await _get_project_property_recipients(project)
    if project_ids is not None:
        logger.debug(
            "Using project property recipients for %r: %s",
            project,
            project_ids,
        )
        return project_ids

    # 2. Fall back to the env var
    settings = get_settings()
    raw_env = settings.weekly_report_notify.strip() if settings.weekly_report_notify else ""

    if not raw_env:
        return []

    if raw_env.lower() == _PROJECT_LEADS_SENTINEL:
        # "project-leads" is a sentinel — attempt the property lookup explicitly
        # (it already returned None above, so there are no project-level leads)
        logger.debug(
            "FORGE_WEEKLY_REPORT_NOTIFY='project-leads' but no project property set for %r; "
            "no recipients.",
            project,
        )
        return []

    env_ids = _parse_account_ids(raw_env)
    logger.debug(
        "Using env var recipients for %r: %s",
        project,
        env_ids,
    )
    return env_ids


async def notify_report_ready(
    ticket_key: str,
    recipients: list[str],
    *,
    jira_base_url: str = "",
) -> None:
    """Post a notification comment on the report ticket mentioning recipients.

    The comment body includes:
    - A brief summary announcing the report is ready.
    - A link to the report ticket.
    - Mentions for each recipient, so they receive a Jira notification.

    Recipients that appear to be invalid (empty string or clearly
    non-account-ID-shaped values) are skipped with a warning log.

    Args:
        ticket_key: Jira issue key of the weekly-report ticket (e.g. ``"PROJ-42"``).
        recipients: List of Jira account IDs to mention.
        jira_base_url: Override for the Jira base URL used in the ticket link.
            When empty, the value from settings is used.  Useful for tests.

    Returns:
        None.  The comment is posted as a side effect.
    """
    if not recipients:
        logger.debug("notify_report_ready: no recipients — skipping comment on %s", ticket_key)
        return

    settings = get_settings()
    base_url = (jira_base_url or settings.jira_base_url).rstrip("/")
    ticket_url = f"{base_url}/browse/{ticket_key}"

    # Validate and build mention strings, skipping obviously invalid IDs
    mention_parts: list[str] = []
    for account_id in recipients:
        if not account_id or not isinstance(account_id, str):
            logger.warning(
                "notify_report_ready: skipping invalid account_id %r on ticket %s",
                account_id,
                ticket_key,
            )
            continue
        # Basic sanity check: account IDs should be non-empty strings without
        # spaces or commas. This guards against accidentally receiving raw
        # comma-separated strings that were not split properly.
        if " " in account_id or "," in account_id:
            logger.warning(
                "notify_report_ready: skipping malformed account_id %r (contains space or comma)"
                " on ticket %s",
                account_id,
                ticket_key,
            )
            continue
        mention_parts.append(_format_mention(account_id))

    if not mention_parts:
        logger.warning(
            "notify_report_ready: all recipients were invalid — no comment posted on %s",
            ticket_key,
        )
        return

    mentions_str = " ".join(mention_parts)
    comment_body = (
        f"📊 *Weekly report is ready:* [{ticket_key}|{ticket_url}]\n\n"
        f"The Forge weekly report has been generated and is available on the ticket above. "
        f"Please review the report for workflow activity, cycle time trends, and any bottlenecks "
        f"identified during the reporting period.\n\n"
        f"Notifying: {mentions_str}"
    )

    jira = JiraClient()
    try:
        await jira.add_comment(ticket_key, comment_body)
        logger.info(
            "Posted notification comment on %s for %d recipient(s)",
            ticket_key,
            len(mention_parts),
        )
    except Exception as exc:
        logger.error(
            "Failed to post notification comment on %s: %s",
            ticket_key,
            exc,
        )
        raise
    finally:
        await jira.close()
