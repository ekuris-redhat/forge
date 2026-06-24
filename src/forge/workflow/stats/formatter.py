"""Jira wiki markup formatter for workflow statistics summaries.

This module transforms StatsState data into Jira wiki markup suitable for
posting as a comment on the associated Jira ticket at the end of a workflow run.
"""

from forge.workflow.stats import (
    ALL_FEATURE_STAGES,
    StageStats,
    StatsState,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum length for outcome_detail before truncation.
_MAX_DETAIL_LEN = 200

#: Display labels for each stage key, in the order they appear in the table.
_STAGE_LABELS: dict[str, str] = {
    "prd": "PRD",
    "spec": "Spec",
    "epics": "Epics",
    "tasks": "Tasks",
    "implementation": "Implementation",
    "ci": "CI",
    "review": "Review",
    # Bug workflow stages (if needed in future extensions)
    "triage": "Triage",
    "rca": "RCA",
    "planning": "Planning",
}

#: Em-dash used when a stage was never executed.
_DASH = "\u2014"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, max_len: int = _MAX_DETAIL_LEN) -> str:
    """Return *text* truncated to *max_len* characters with '...' suffix.

    If *text* is already within the limit it is returned unchanged.
    """
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _fmt_seconds(seconds: float) -> str:
    """Format a duration in seconds to a human-readable string (e.g. '1h 23m 45s')."""
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _fmt_tokens(count: int) -> str:
    """Format a token count with thousands separators."""
    return f"{count:,}"


def _build_stage_row(label: str, stage: StageStats | None) -> str:
    """Return a single Jira table row for a workflow stage.

    If *stage* is None (never executed), all metric columns show '—'.
    """
    if stage is None:
        return f"|{label}|{_DASH}|{_DASH}|{_DASH}|{_DASH}|{_DASH}|"

    iterations = stage.get("iteration_count", 0)
    machine_time = _fmt_seconds(stage.get("machine_time_seconds", 0.0))
    human_time = _fmt_seconds(stage.get("human_time_seconds", 0.0))
    input_tok = _fmt_tokens(stage.get("input_tokens", 0))
    output_tok = _fmt_tokens(stage.get("output_tokens", 0))

    return f"|{label}|{iterations}|{machine_time}|{human_time}|{input_tok}|{output_tok}|"


def _build_totals_row(stages: dict[str, StageStats]) -> str:
    """Return the aggregate token totals row summed across all stages."""
    total_input = sum(s.get("input_tokens", 0) for s in stages.values())
    total_output = sum(s.get("output_tokens", 0) for s in stages.values())
    return f"|*Total*|—|—|—|*{_fmt_tokens(total_input)}*|*{_fmt_tokens(total_output)}*|"


def _build_outcome_str(outcome: str, outcome_detail: str | None) -> str:
    """Construct the formatted outcome string for display.

    Supported outcome values:
        ``"completed"``  → ``"Completed"``
        ``"blocked"``    → ``"Blocked: <reason>"``
        ``"failed"``     → ``"Failed: <error>"``

    The *outcome* parameter is matched case-insensitively. Any detail longer
    than 200 characters is truncated with '...' suffix.
    """
    key = outcome.lower()
    if key == "completed":
        return "Completed"
    detail = _truncate(outcome_detail or "") if outcome_detail else ""
    if key == "blocked":
        if detail:
            return f"Blocked: {detail}"
        return "Blocked"
    if key == "failed":
        if detail:
            return f"Failed: {detail}"
        return "Failed"
    # Fallback for unknown outcome values — display as-is with optional detail.
    if detail:
        return f"{outcome}: {detail}"
    return outcome


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def format_stats_summary(
    stats: StatsState,
    outcome: str,
    outcome_detail: str | None = None,
) -> str:
    """Format a StatsState snapshot into a Jira wiki markup comment.

    The generated comment includes:
    * A stage-by-stage metrics table (iterations, machine time, human time,
      input tokens, output tokens).
    * An aggregate token totals row.
    * A PR links section (omitted when no PRs were created).
    * A CI cycles line.
    * A final outcome field.

    Args:
        stats: The workflow statistics state to format.
        outcome: Outcome category — one of ``"completed"``, ``"blocked"``, or
            ``"failed"`` (matched case-insensitively).
        outcome_detail: Optional elaboration on the outcome (e.g. the blocking
            reason or error message).  Truncated to 200 characters if longer.

    Returns:
        A Jira wiki markup string ready to post as a ticket comment.
    """
    stages: dict[str, StageStats] = stats.get("stats_stages") or {}
    pr_urls: list[str] = stats.get("stats_pr_urls") or []
    ci_cycles: int = stats.get("stats_ci_cycles") or 0

    lines: list[str] = []

    # ------------------------------------------------------------------
    # Stage metrics table
    # ------------------------------------------------------------------
    lines.append("h3. Workflow Statistics")
    lines.append("")
    lines.append("||Stage||Iterations||Machine Time||Human Time||Input Tokens||Output Tokens||")

    for stage_key in ALL_FEATURE_STAGES:
        label = _STAGE_LABELS.get(stage_key, stage_key.title())
        stage_data = stages.get(stage_key)
        lines.append(_build_stage_row(label, stage_data))

    # Aggregate totals row (always shown, even when no stages ran)
    lines.append(_build_totals_row(stages))

    # ------------------------------------------------------------------
    # PR links section (omitted when no PRs)
    # ------------------------------------------------------------------
    if pr_urls:
        lines.append("")
        lines.append("*Pull Requests*")
        for url in pr_urls:
            lines.append(f"* [{url}|{url}]")

    # ------------------------------------------------------------------
    # CI cycles
    # ------------------------------------------------------------------
    lines.append("")
    lines.append(f"*CI Cycles:* {ci_cycles}")

    # ------------------------------------------------------------------
    # Outcome
    # ------------------------------------------------------------------
    lines.append("")
    outcome_str = _build_outcome_str(outcome, outcome_detail)
    lines.append(f"*Outcome:* {outcome_str}")

    return "\n".join(lines)
