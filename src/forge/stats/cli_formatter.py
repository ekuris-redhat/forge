"""CLI formatter for workflow statistics terminal output.

This module renders ``WorkflowStats`` as human-readable ASCII tables or
pretty-printed JSON, suitable for terminal display via ``forge stats``.

It complements the Jira wiki markup formatter in
``forge.workflow.stats.formatter`` — that module targets Jira comments
while this one targets terminal output.

Usage::

    from forge.stats.cli_formatter import format_stats_table, format_stats_json

    # ASCII table for terminal display
    print(format_stats_table(stats))

    # Pretty-printed JSON for scripting
    print(format_stats_json(stats))
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from forge.stats.retrieval import WorkflowStats
from forge.workflow.stats import (
    ALL_BUG_STAGES,
    ALL_FEATURE_STAGES,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Em-dash used when a stage was never executed (matches Jira formatter).
_DASH = "\u2014"

#: Display labels for each stage key.
_STAGE_LABELS: dict[str, str] = {
    "prd": "PRD",
    "spec": "Spec",
    "epics": "Epics",
    "tasks": "Tasks",
    "implementation": "Implementation",
    "ci": "CI",
    "review": "Review",
    "triage": "Triage",
    "rca": "RCA",
    "planning": "Planning",
}

#: ANSI colour codes used for optional colorized output.
_COLOR_GREEN = "\033[32m"
_COLOR_RED = "\033[31m"
_COLOR_YELLOW = "\033[33m"
_COLOR_BOLD = "\033[1m"
_COLOR_RESET = "\033[0m"

# Column header names.
_HEADERS = ("Stage", "Iterations", "Machine Time", "Human Time", "Tokens In", "Tokens Out")

# ---------------------------------------------------------------------------
# Internal helpers — formatting primitives
# ---------------------------------------------------------------------------


def _fmt_seconds(seconds: float) -> str:
    """Format a duration in seconds to a compact string (e.g. ``'1h 23m 45s'``).

    Zero-value components are elided: ``60`` → ``'1m 0s'``,
    ``3601`` → ``'1h 0m 1s'``.
    """
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _fmt_tokens(count: int) -> str:
    """Format a token count with thousands separators (e.g. ``'1,234,567'``)."""
    return f"{count:,}"


def _truncate(text: str, max_len: int) -> str:
    """Truncate *text* to *max_len* characters, appending ``'...'`` if needed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _colorize(text: str, color: str, *, use_color: bool) -> str:
    """Wrap *text* in ANSI *color* escape codes if *use_color* is True."""
    if not use_color:
        return text
    return f"{color}{text}{_COLOR_RESET}"


# ---------------------------------------------------------------------------
# Internal helpers — table building
# ---------------------------------------------------------------------------


def _stage_row_values(label: str, stage: dict | None) -> tuple[str, str, str, str, str, str]:
    """Return the six cell values for a single stage row.

    When *stage* is ``None`` (stage was never executed), all metric cells
    contain the em-dash sentinel ``"—"``.
    """
    if stage is None:
        return (label, _DASH, _DASH, _DASH, _DASH, _DASH)

    iterations = str(stage.get("iteration_count", 0))
    machine_time = _fmt_seconds(stage.get("machine_time_seconds", 0.0))
    human_time = _fmt_seconds(stage.get("human_time_seconds", 0.0))
    tokens_in = _fmt_tokens(stage.get("input_tokens", 0))
    tokens_out = _fmt_tokens(stage.get("output_tokens", 0))
    return (label, iterations, machine_time, human_time, tokens_in, tokens_out)


def _totals_row_values(stages: dict[str, dict]) -> tuple[str, str, str, str, str, str]:
    """Return the six cell values for the summary totals row."""
    total_machine = sum(s.get("machine_time_seconds", 0.0) for s in stages.values())
    total_human = sum(s.get("human_time_seconds", 0.0) for s in stages.values())
    total_in = sum(s.get("input_tokens", 0) for s in stages.values())
    total_out = sum(s.get("output_tokens", 0) for s in stages.values())
    return (
        "TOTAL",
        "",
        _fmt_seconds(total_machine),
        _fmt_seconds(total_human),
        _fmt_tokens(total_in),
        _fmt_tokens(total_out),
    )


def _render_table(
    rows: list[tuple[str, ...]],
    col_widths: list[int],
    *,
    header_sep: bool = True,
) -> list[str]:
    """Render *rows* as an ASCII table given pre-computed *col_widths*.

    Returns a list of strings (one per line).  The first row is always the
    header; a separator line is inserted below it when *header_sep* is True.
    """

    def _row_line(cells: tuple[str, ...]) -> str:
        padded = [cell.ljust(col_widths[i]) for i, cell in enumerate(cells)]
        return "| " + " | ".join(padded) + " |"

    def _sep_line() -> str:
        return "+-" + "-+-".join("-" * w for w in col_widths) + "-+"

    lines: list[str] = []
    for i, row in enumerate(rows):
        lines.append(_row_line(row))
        if i == 0 and header_sep:
            lines.append(_sep_line())
    lines.append(_sep_line())
    return lines


def _compute_col_widths(
    rows: list[tuple[str, ...]],
    max_col_width: int = 20,
) -> list[int]:
    """Compute column widths from all rows, capping at *max_col_width*."""
    if not rows:
        return []
    n_cols = len(rows[0])
    widths = [0] * n_cols
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], min(len(cell), max_col_width))
    return widths


def _determine_display_stages(stages: dict[str, dict]) -> list[str]:
    """Return the ordered list of stage keys to display.

    Uses ``ALL_FEATURE_STAGES`` by default.  If the workflow contains any
    bug-only stages (``triage``, ``rca``, ``planning``) that are absent from
    the feature list, the bug stage ordering is preferred.
    """
    bug_only = {"triage", "rca", "planning"}
    if any(k in stages for k in bug_only):
        return ALL_BUG_STAGES
    return ALL_FEATURE_STAGES


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def format_stats_table(
    stats: WorkflowStats,
    *,
    use_color: bool = False,
    max_col_width: int = 20,
) -> str:
    """Render *stats* as a human-readable ASCII table for terminal display.

    The output includes:

    * A metadata block: ticket key, outcome, CI cycles, workflow run ID.
    * A stage-by-stage metrics table with columns:
      Stage | Iterations | Machine Time | Human Time | Tokens In | Tokens Out
    * A summary totals row (times and tokens summed across all stages).
    * A PR links section (omitted when no PRs were created).

    Stages that were never executed show ``"—"`` in all metric columns,
    consistent with the Jira formatter.

    Args:
        stats: The ``WorkflowStats`` instance to format.
        use_color: When ``True``, ANSI color codes are applied: green for
            "Completed", red for "Failed", yellow for "Blocked".
        max_col_width: Maximum width of any table column (characters).
            Longer values are truncated with ``'...'``.  Defaults to 20.

    Returns:
        A multi-line string suitable for printing to a terminal.
    """
    lines: list[str] = []

    # ------------------------------------------------------------------
    # Metadata block
    # ------------------------------------------------------------------
    outcome_raw = stats.outcome or "In Progress"
    outcome_lower = outcome_raw.lower()

    if use_color:
        if outcome_lower == "completed":
            outcome_display = _colorize(outcome_raw, _COLOR_GREEN, use_color=True)
        elif outcome_lower.startswith("failed"):
            outcome_display = _colorize(outcome_raw, _COLOR_RED, use_color=True)
        elif outcome_lower.startswith("blocked"):
            outcome_display = _colorize(outcome_raw, _COLOR_YELLOW, use_color=True)
        else:
            outcome_display = outcome_raw
    else:
        outcome_display = outcome_raw

    lines.append(_colorize("Workflow Statistics", _COLOR_BOLD, use_color=use_color))
    lines.append("")
    lines.append(f"  Ticket:       {stats.ticket_key}")
    lines.append(f"  Outcome:      {outcome_display}")
    if stats.outcome_reason:
        reason = _truncate(stats.outcome_reason, 80)
        lines.append(f"  Reason:       {reason}")
    lines.append(f"  CI Cycles:    {stats.ci_cycles}")
    if stats.workflow_run_id:
        lines.append(f"  Run ID:       {stats.workflow_run_id}")

    # Derive created_at / updated_at from stage timestamps.
    all_started = [s.get("started_at") for s in stats.stages.values() if s.get("started_at")]
    all_ended = [s.get("ended_at") for s in stats.stages.values() if s.get("ended_at")]
    if all_started:
        lines.append(f"  Started:      {min(all_started)}")
    if all_ended:
        lines.append(f"  Last Updated: {max(all_ended)}")

    lines.append("")

    # ------------------------------------------------------------------
    # Stage metrics table
    # ------------------------------------------------------------------
    display_stages = _determine_display_stages(stats.stages)

    data_rows: list[tuple[str, str, str, str, str, str]] = []
    for stage_key in display_stages:
        label = _STAGE_LABELS.get(stage_key, stage_key.title())
        stage_data = stats.stages.get(stage_key)
        data_rows.append(_stage_row_values(label, stage_data))

    # Totals row (only meaningful when at least one stage ran)
    totals = _totals_row_values(stats.stages)
    data_rows.append(totals)

    # Truncate cell values to max_col_width before computing widths.
    truncated_rows: list[tuple[str, ...]] = []
    for row in data_rows:
        truncated_rows.append(tuple(_truncate(cell, max_col_width) for cell in row))

    all_rows: list[tuple[str, ...]] = [_HEADERS, *truncated_rows]
    col_widths = _compute_col_widths(all_rows, max_col_width=max_col_width)
    table_lines = _render_table(all_rows, col_widths)
    lines.extend(table_lines)

    # ------------------------------------------------------------------
    # PR links section (omitted when no PRs)
    # ------------------------------------------------------------------
    if stats.pr_urls:
        lines.append("")
        lines.append("Pull Requests:")
        for url in stats.pr_urls:
            lines.append(f"  {url}")

    return "\n".join(lines)


def format_stats_json(stats: WorkflowStats) -> str:
    """Render *stats* as pretty-printed JSON.

    The JSON document includes all ``WorkflowStats`` fields with their
    proper Python types serialised to JSON-safe equivalents.  The output
    is indented with 2 spaces and keys are sorted alphabetically for
    stable, diff-friendly output.

    Args:
        stats: The ``WorkflowStats`` instance to serialise.

    Returns:
        A pretty-printed JSON string.
    """
    payload: dict = {
        "ticket_key": stats.ticket_key,
        "outcome": stats.outcome,
        "outcome_reason": stats.outcome_reason,
        "ci_cycles": stats.ci_cycles,
        "comment_posted": stats.comment_posted,
        "workflow_run_id": stats.workflow_run_id,
        "pr_urls": stats.pr_urls,
        "stages": {
            stage_key: {
                "stage_name": stage_data.get("stage_name", stage_key),
                "iteration_count": stage_data.get("iteration_count", 0),
                "machine_time_seconds": stage_data.get("machine_time_seconds", 0.0),
                "human_time_seconds": stage_data.get("human_time_seconds", 0.0),
                "input_tokens": stage_data.get("input_tokens", 0),
                "output_tokens": stage_data.get("output_tokens", 0),
                "started_at": stage_data.get("started_at"),
                "ended_at": stage_data.get("ended_at"),
            }
            for stage_key, stage_data in stats.stages.items()
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True)
