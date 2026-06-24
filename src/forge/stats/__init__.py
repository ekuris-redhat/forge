"""Stats service package for Forge workflow statistics.

This package provides a unified interface for retrieving and validating
workflow statistics data from LangGraph checkpoints. It is consumed by
both Jira command handlers and CLI commands.

Public API
----------
``WorkflowStats``
    Dataclass containing fully-validated stats fields extracted from a
    checkpoint.

``get_workflow_stats(ticket_key)``
    Async function that retrieves stats for a ticket.  Returns ``None``
    when no checkpoint or no stats data is found.

``get_workflow_stats_or_error(ticket_key)``
    Async function that returns ``(stats, error_message)``; never raises.
    Suitable for CLI / command-handler callers that need a display-ready
    error string instead of an exception.
"""

from forge.stats.retrieval import (
    WorkflowStats,
    get_workflow_stats,
    get_workflow_stats_or_error,
)

__all__ = [
    "WorkflowStats",
    "get_workflow_stats",
    "get_workflow_stats_or_error",
]
