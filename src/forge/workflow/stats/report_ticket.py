"""Report ticket resolution and auto-creation for weekly reports.

This module provides functions to create or update a dedicated "Weekly Report"
ticket in Jira that stores the weekly report content, enabling historical
tracking and Jira-native access.

Usage::

    from datetime import date
    from forge.workflow.stats.report_ticket import ensure_report_ticket

    ticket_key = await ensure_report_ticket(
        project="PROJ",
        week_start=date(2024, 1, 8),
        report_markdown="## Weekly Report\\n...",
    )
    print(f"Report ticket: {ticket_key}")
"""

from __future__ import annotations

import logging
from datetime import date

from forge.integrations.jira.client import JiraClient

logger = logging.getLogger(__name__)

#: Labels applied to every report ticket.
REPORT_LABELS: list[str] = ["forge:weekly-report", "forge:generated"]

#: Issue type used for report tickets.
REPORT_ISSUE_TYPE: str = "Task"


def _report_summary(project: str, week_start: date) -> str:
    """Build the standard summary string for a report ticket.

    Args:
        project: Jira project key (e.g. ``"PROJ"``).
        week_start: The Monday (or first day) of the reporting week.

    Returns:
        Summary string in the form
        ``"Forge Weekly Report - PROJ - Week of 2024-01-08"``.
    """
    return f"Forge Weekly Report - {project} - Week of {week_start}"


def _report_jql(project: str, week_start: date) -> str:
    """Build the JQL query to locate an existing report ticket.

    Args:
        project: Jira project key.
        week_start: The first day of the reporting week.

    Returns:
        JQL string.
    """
    week_str = str(week_start)
    return (
        f'project = "{project}" '
        f'AND labels = "forge:weekly-report" '
        f'AND summary ~ "Week of {week_str}"'
    )


async def resolve_report_ticket(project: str, week_start: date) -> str | None:
    """Find an existing report ticket for the given project and week.

    Searches Jira using JQL:
    ``project = {project} AND labels = "forge:weekly-report"
    AND summary ~ "Week of {week_start}"``.

    Args:
        project: Jira project key (e.g. ``"PROJ"``).
        week_start: The first day of the reporting week.

    Returns:
        The ticket key (e.g. ``"PROJ-42"``) if found, or ``None``.
    """
    jql = _report_jql(project, week_start)
    jira = JiraClient()
    try:
        issues = await jira.search_issues(
            jql=jql,
            fields=["summary", "labels"],
            max_results=5,
        )
    finally:
        await jira.close()

    if not issues:
        logger.debug(
            "No existing report ticket found for project=%r week_start=%s",
            project,
            week_start,
        )
        return None

    # Return the first (most relevant) match.
    ticket_key = issues[0].key
    logger.info(
        "Found existing report ticket %s for project=%r week_start=%s",
        ticket_key,
        project,
        week_start,
    )
    return ticket_key


async def create_report_ticket(
    project: str,
    week_start: date,
    report_markdown: str,
) -> str:
    """Create a new report ticket with the given report as its description.

    Args:
        project: Jira project key (e.g. ``"PROJ"``).
        week_start: The first day of the reporting week.
        report_markdown: Full report content (Markdown / Jira wiki markup).

    Returns:
        The key of the newly created ticket (e.g. ``"PROJ-42"``).
    """
    summary = _report_summary(project, week_start)
    jira = JiraClient()
    try:
        ticket_key = await jira.create_task(
            project_key=project,
            summary=summary,
            description=report_markdown,
            labels=REPORT_LABELS,
        )
    finally:
        await jira.close()

    logger.info(
        "Created report ticket %s for project=%r week_start=%s",
        ticket_key,
        project,
        week_start,
    )
    return ticket_key


async def update_report_ticket(ticket_key: str, report_markdown: str) -> None:
    """Update the description of an existing report ticket.

    Does not create a duplicate — only updates the description field of the
    ticket identified by *ticket_key*.

    Args:
        ticket_key: The Jira issue key to update (e.g. ``"PROJ-42"``).
        report_markdown: New report content (Markdown / Jira wiki markup).
    """
    jira = JiraClient()
    try:
        await jira.update_description(ticket_key, report_markdown)
    finally:
        await jira.close()

    logger.info("Updated description for report ticket %s", ticket_key)


async def ensure_report_ticket(
    project: str,
    week_start: date,
    report_markdown: str,
) -> str:
    """Resolve or create the report ticket, then update its description.

    This function is idempotent — calling it twice with the same arguments
    produces the same result (the existing ticket is updated in-place rather
    than a duplicate being created).

    Steps:

    1. Search for an existing report ticket via :func:`resolve_report_ticket`.
    2. If none exists, create one via :func:`create_report_ticket`.
    3. Update the description with *report_markdown* via
       :func:`update_report_ticket`.

    Args:
        project: Jira project key (e.g. ``"PROJ"``).
        week_start: The first day of the reporting week.
        report_markdown: Full report content (Markdown / Jira wiki markup).

    Returns:
        The key of the report ticket (existing or newly created).
    """
    ticket_key = await resolve_report_ticket(project, week_start)

    if ticket_key is None:
        ticket_key = await create_report_ticket(project, week_start, report_markdown)
    else:
        await update_report_ticket(ticket_key, report_markdown)

    return ticket_key
