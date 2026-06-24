"""Weekly report formatters for CLI, Markdown, and JSON output.

This module renders :class:`WeeklyReportData` into human-readable terminal
output, exportable Markdown (suitable for Jira posting or file export), and
machine-readable JSON for tooling integration.

Usage::

    from forge.workflow.stats.weekly_formatter import (
        format_weekly_report_cli,
        format_weekly_report_markdown,
        format_weekly_report_json,
    )

    report = await collect_weekly_data("AISOS")

    # Terminal output
    print(format_weekly_report_cli(report))

    # Save Markdown to file
    with open("weekly.md", "w") as f:
        f.write(format_weekly_report_markdown(report))

    # JSON for scripting
    print(format_weekly_report_json(report))
"""

from __future__ import annotations

import json

from forge.workflow.stats.weekly_report import (
    BottleneckAnalysis,
    FeatureRollup,
    TicketSummary,
    WeeklyReportData,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Em-dash used for absent / N/A values.
_DASH = "\u2014"

#: Display labels for workflow stage keys.
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


# ---------------------------------------------------------------------------
# Internal formatting primitives
# ---------------------------------------------------------------------------


def _format_duration(seconds: float) -> str:
    """Format *seconds* into a human-readable duration string.

    Examples::

        _format_duration(0)        → "0s"
        _format_duration(65)       → "1m 5s"
        _format_duration(3662)     → "1h 1m 2s"
        _format_duration(90061)    → "25h 1m 1s"

    Args:
        seconds: Non-negative duration in seconds.

    Returns:
        A compact human-readable string such as ``"3h 42m"`` or ``"7m 30s"``.
        Hours are always shown when present; minutes are shown when ≥ 1 or
        when hours are shown; seconds are always shown.
    """
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _format_token_count(count: int) -> str:
    """Format *count* as an abbreviated token count string.

    Large numbers are abbreviated with metric suffixes:

    * ``< 1 000``       → raw integer (e.g. ``"999"``)
    * ``1 000–999 999`` → ``"Nk"`` or ``"N.Mk"`` (e.g. ``"31k"``, ``"1.5k"``)
    * ``≥ 1 000 000``   → ``"NM"`` or ``"N.MM"`` (e.g. ``"1M"``, ``"1.5M"``)

    Examples::

        _format_token_count(999)       → "999"
        _format_token_count(1000)      → "1k"
        _format_token_count(1500)      → "1.5k"
        _format_token_count(31000)     → "31k"
        _format_token_count(1000000)   → "1M"
        _format_token_count(1500000)   → "1.5M"

    Args:
        count: Non-negative token count.

    Returns:
        A compact abbreviated string representation.
    """
    if count < 1_000:
        return str(count)
    if count < 1_000_000:
        value = count / 1_000
        if value == int(value):
            return f"{int(value)}k"
        return f"{value:.1f}k"
    value = count / 1_000_000
    if value == int(value):
        return f"{int(value)}M"
    return f"{value:.1f}M"


def _format_bottleneck_section(bottlenecks: BottleneckAnalysis) -> str:
    """Render a *BottleneckAnalysis* as a plain-text section.

    The section includes:

    * Total tickets analysed
    * Slowest stage (or N/A)
    * CI fix rate as a percentage
    * Top revised stages (up to 3)
    * Stage average durations table

    Args:
        bottlenecks: The bottleneck data to render.

    Returns:
        A multi-line plain-text string (no trailing newline).
    """
    lines: list[str] = []

    lines.append(f"  Tickets Analysed : {bottlenecks.total_tickets_analyzed}")

    slowest = bottlenecks.slowest_stage
    if slowest:
        avg_dur = bottlenecks.avg_stage_durations.get(slowest, 0.0)
        label = _STAGE_LABELS.get(slowest, slowest.title())
        lines.append(f"  Slowest Stage    : {label} (avg {_format_duration(avg_dur)})")
    else:
        lines.append(f"  Slowest Stage    : {_DASH}")

    ci_pct = bottlenecks.ci_fix_rate * 100.0
    lines.append(f"  CI Fix Rate      : {ci_pct:.0f}%")

    if bottlenecks.most_revised_stages:
        top = bottlenecks.most_revised_stages[:3]
        top_labels = [_STAGE_LABELS.get(s, s.title()) for s in top]
        lines.append(f"  Most Revised     : {', '.join(top_labels)}")
    else:
        lines.append(f"  Most Revised     : {_DASH}")

    if bottlenecks.avg_stage_durations:
        lines.append("")
        lines.append("  Stage Avg Durations:")
        for stage_key, avg_secs in sorted(bottlenecks.avg_stage_durations.items()):
            label = _STAGE_LABELS.get(stage_key, stage_key.title())
            lines.append(f"    {label:<16} {_format_duration(avg_secs)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal section builders
# ---------------------------------------------------------------------------


def _ticket_list_summary(tickets: list[TicketSummary]) -> list[str]:
    """Return a list of formatted lines for a ticket list subsection (CLI)."""
    if not tickets:
        return ["    (none)"]
    lines: list[str] = []
    for t in tickets:
        duration_str = (
            _format_duration(t.duration_seconds) if t.duration_seconds is not None else _DASH
        )
        tokens_str = _format_token_count(t.input_tokens + t.output_tokens)
        lines.append(
            f"    {t.ticket_key:<16} {t.ticket_type:<10} dur={duration_str:<10} tokens={tokens_str}"
        )
    return lines


def _token_by_stage_section(tokens_by_stage: dict[str, tuple[int, int]]) -> list[str]:
    """Return CLI lines for the token breakdown by stage."""
    if not tokens_by_stage:
        return ["    (no stage data)"]
    lines: list[str] = []
    for stage_key, (in_tok, out_tok) in sorted(tokens_by_stage.items()):
        label = _STAGE_LABELS.get(stage_key, stage_key.title())
        total = in_tok + out_tok
        lines.append(
            f"    {label:<16} in={_format_token_count(in_tok):<8} "
            f"out={_format_token_count(out_tok):<8} "
            f"total={_format_token_count(total)}"
        )
    return lines


def _feature_rollup_section_cli(feature_rollups: dict[str, FeatureRollup]) -> list[str]:
    """Return CLI lines for the Feature rollup section."""
    if not feature_rollups:
        return []
    lines: list[str] = ["", "Feature Rollup", "=" * 60]
    for feature_key, rollup in sorted(feature_rollups.items()):
        summary = rollup.feature_summary or "(no summary)"
        lines.append(f"  {feature_key}: {summary}")
        total_tickets = len(rollup.linked_tickets)
        lines.append(
            f"    Tickets : {total_tickets} total, "
            f"{rollup.tickets_completed} completed, "
            f"{rollup.tickets_in_progress} in progress"
        )
        lines.append(f"    Progress: {rollup.completion_percentage:.0f}%")
        tokens_total = rollup.total_input_tokens + rollup.total_output_tokens
        lines.append(f"    Tokens  : {_format_token_count(tokens_total)}")
        if rollup.total_duration is not None:
            lines.append(f"    Duration: {_format_duration(rollup.total_duration)}")
        lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def format_weekly_report_cli(data: WeeklyReportData) -> str:
    """Render *data* as a terminal-friendly plain text weekly report.

    The output matches the design spec format (Section 4) and includes:

    * Report header (project, period, date range)
    * Summary section (ticket counts, avg cycle time, token totals)
    * Ticket breakdown by status (completed, in-progress, blocked)
    * Token usage by stage
    * Bottleneck analysis
    * Feature rollup section (when feature_rollups is populated)

    Args:
        data: Aggregated weekly report data.

    Returns:
        A multi-line plain text string suitable for terminal display.
    """
    lines: list[str] = []

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    period_label = f"Last {data.period_days} days"
    lines.append("=" * 60)
    lines.append(f"  WEEKLY REPORT — {data.project}")
    lines.append(f"  Period : {period_label}")
    lines.append(f"  From   : {data.report_start}")
    lines.append(f"  To     : {data.report_end}")
    lines.append("=" * 60)
    lines.append("")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    n_completed = len(data.completed_tickets)
    n_in_progress = len(data.in_progress_tickets)
    n_blocked = len(data.blocked_tickets)
    n_total = n_completed + n_in_progress + n_blocked

    avg_cycle = _format_duration(data.avg_cycle_time) if data.avg_cycle_time is not None else _DASH
    total_tokens = data.total_input_tokens + data.total_output_tokens

    lines.append("Summary")
    lines.append("-" * 40)
    lines.append(f"  Total Tickets  : {n_total}")
    lines.append(f"  Completed      : {n_completed}")
    lines.append(f"  In Progress    : {n_in_progress}")
    lines.append(f"  Blocked        : {n_blocked}")
    lines.append(f"  Avg Cycle Time : {avg_cycle}")
    lines.append(f"  Total Tokens   : {_format_token_count(total_tokens)}")
    lines.append(f"  Input Tokens   : {_format_token_count(data.total_input_tokens)}")
    lines.append(f"  Output Tokens  : {_format_token_count(data.total_output_tokens)}")
    lines.append("")

    # ------------------------------------------------------------------
    # Ticket lists
    # ------------------------------------------------------------------
    lines.append("Completed Tickets")
    lines.append("-" * 40)
    lines.extend(_ticket_list_summary(data.completed_tickets))
    lines.append("")

    lines.append("In-Progress Tickets")
    lines.append("-" * 40)
    lines.extend(_ticket_list_summary(data.in_progress_tickets))
    lines.append("")

    lines.append("Blocked Tickets")
    lines.append("-" * 40)
    lines.extend(_ticket_list_summary(data.blocked_tickets))
    lines.append("")

    # ------------------------------------------------------------------
    # Token usage by stage
    # ------------------------------------------------------------------
    lines.append("Token Usage by Stage")
    lines.append("-" * 40)
    lines.extend(_token_by_stage_section(data.tokens_by_stage))
    lines.append("")

    # ------------------------------------------------------------------
    # Bottleneck analysis
    # ------------------------------------------------------------------
    lines.append("Bottleneck Analysis")
    lines.append("-" * 40)
    lines.append(_format_bottleneck_section(data.bottlenecks))
    lines.append("")

    # ------------------------------------------------------------------
    # Feature rollup (when populated)
    # ------------------------------------------------------------------
    rollup_lines = _feature_rollup_section_cli(data.feature_rollups)
    if rollup_lines:
        lines.extend(rollup_lines)

    return "\n".join(lines)


def format_weekly_report_markdown(data: WeeklyReportData) -> str:
    """Render *data* as a Markdown weekly report.

    The output is valid GitHub-flavored Markdown with headers and tables,
    suitable for:

    * Saving to a ```.md`` file
    * Posting to Jira as a Markdown code block or using a Markdown plugin
    * Sharing in Slack/Teams channels

    Args:
        data: Aggregated weekly report data.

    Returns:
        A Markdown string.
    """
    lines: list[str] = []

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    period_label = f"Last {data.period_days} Days"
    lines.append(f"# Weekly Report — {data.project}")
    lines.append("")
    lines.append(f"**Period:** {period_label}  ")
    lines.append(f"**From:** {data.report_start}  ")
    lines.append(f"**To:** {data.report_end}")
    lines.append("")

    # ------------------------------------------------------------------
    # Summary table
    # ------------------------------------------------------------------
    n_completed = len(data.completed_tickets)
    n_in_progress = len(data.in_progress_tickets)
    n_blocked = len(data.blocked_tickets)
    n_total = n_completed + n_in_progress + n_blocked

    avg_cycle = _format_duration(data.avg_cycle_time) if data.avg_cycle_time is not None else _DASH
    total_tokens = data.total_input_tokens + data.total_output_tokens

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total Tickets | {n_total} |")
    lines.append(f"| Completed | {n_completed} |")
    lines.append(f"| In Progress | {n_in_progress} |")
    lines.append(f"| Blocked | {n_blocked} |")
    lines.append(f"| Avg Cycle Time | {avg_cycle} |")
    lines.append(f"| Total Tokens | {_format_token_count(total_tokens)} |")
    lines.append(f"| Input Tokens | {_format_token_count(data.total_input_tokens)} |")
    lines.append(f"| Output Tokens | {_format_token_count(data.total_output_tokens)} |")
    lines.append("")

    # ------------------------------------------------------------------
    # Tickets table
    # ------------------------------------------------------------------
    def _ticket_md_row(t: TicketSummary) -> str:
        duration_str = (
            _format_duration(t.duration_seconds) if t.duration_seconds is not None else _DASH
        )
        tokens_str = _format_token_count(t.input_tokens + t.output_tokens)
        return f"| {t.ticket_key} | {t.ticket_type} | {duration_str} | {tokens_str} |"

    ticket_header = "| Ticket | Type | Duration | Tokens |"
    ticket_sep = "|--------|------|----------|--------|"

    lines.append("## Completed Tickets")
    lines.append("")
    if data.completed_tickets:
        lines.append(ticket_header)
        lines.append(ticket_sep)
        for t in data.completed_tickets:
            lines.append(_ticket_md_row(t))
    else:
        lines.append("_No completed tickets this period._")
    lines.append("")

    lines.append("## In-Progress Tickets")
    lines.append("")
    if data.in_progress_tickets:
        lines.append(ticket_header)
        lines.append(ticket_sep)
        for t in data.in_progress_tickets:
            lines.append(_ticket_md_row(t))
    else:
        lines.append("_No in-progress tickets this period._")
    lines.append("")

    lines.append("## Blocked Tickets")
    lines.append("")
    if data.blocked_tickets:
        lines.append(ticket_header)
        lines.append(ticket_sep)
        for t in data.blocked_tickets:
            lines.append(_ticket_md_row(t))
    else:
        lines.append("_No blocked tickets this period._")
    lines.append("")

    # ------------------------------------------------------------------
    # Token usage by stage
    # ------------------------------------------------------------------
    lines.append("## Token Usage by Stage")
    lines.append("")
    if data.tokens_by_stage:
        lines.append("| Stage | Input | Output | Total |")
        lines.append("|-------|-------|--------|-------|")
        for stage_key, (in_tok, out_tok) in sorted(data.tokens_by_stage.items()):
            label = _STAGE_LABELS.get(stage_key, stage_key.title())
            total = in_tok + out_tok
            lines.append(
                f"| {label} | {_format_token_count(in_tok)} "
                f"| {_format_token_count(out_tok)} "
                f"| {_format_token_count(total)} |"
            )
    else:
        lines.append("_No stage token data available._")
    lines.append("")

    # ------------------------------------------------------------------
    # Bottleneck analysis
    # ------------------------------------------------------------------
    b = data.bottlenecks
    lines.append("## Bottleneck Analysis")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Tickets Analysed | {b.total_tickets_analyzed} |")

    slowest = b.slowest_stage
    if slowest:
        avg_dur = b.avg_stage_durations.get(slowest, 0.0)
        slowest_label = _STAGE_LABELS.get(slowest, slowest.title())
        lines.append(f"| Slowest Stage | {slowest_label} (avg {_format_duration(avg_dur)}) |")
    else:
        lines.append(f"| Slowest Stage | {_DASH} |")

    ci_pct = b.ci_fix_rate * 100.0
    lines.append(f"| CI Fix Rate | {ci_pct:.0f}% |")

    if b.most_revised_stages:
        top = b.most_revised_stages[:3]
        top_labels = [_STAGE_LABELS.get(s, s.title()) for s in top]
        lines.append(f"| Most Revised | {', '.join(top_labels)} |")
    else:
        lines.append(f"| Most Revised | {_DASH} |")
    lines.append("")

    if b.avg_stage_durations:
        lines.append("### Stage Average Durations")
        lines.append("")
        lines.append("| Stage | Avg Duration |")
        lines.append("|-------|-------------|")
        for stage_key, avg_secs in sorted(b.avg_stage_durations.items()):
            label = _STAGE_LABELS.get(stage_key, stage_key.title())
            lines.append(f"| {label} | {_format_duration(avg_secs)} |")
        lines.append("")

    # ------------------------------------------------------------------
    # Feature rollup
    # ------------------------------------------------------------------
    if data.feature_rollups:
        lines.append("## Feature Rollup")
        lines.append("")
        lines.append(
            "| Feature | Summary | Tickets | Completed | In Progress | Progress | Tokens |"
        )
        lines.append(
            "|---------|---------|---------|-----------|-------------|----------|--------|"
        )
        for feature_key, rollup in sorted(data.feature_rollups.items()):
            summary = rollup.feature_summary or ""
            total_tickets = len(rollup.linked_tickets)
            tokens_total = rollup.total_input_tokens + rollup.total_output_tokens
            lines.append(
                f"| {feature_key} | {summary} | {total_tickets} "
                f"| {rollup.tickets_completed} | {rollup.tickets_in_progress} "
                f"| {rollup.completion_percentage:.0f}% "
                f"| {_format_token_count(tokens_total)} |"
            )
        lines.append("")

    return "\n".join(lines)


def format_weekly_report_json(data: WeeklyReportData) -> str:
    """Serialise *data* as pretty-printed JSON for tooling integration.

    All dataclass fields are included in the output.  Token counts are left as
    raw integers (not abbreviated) so that downstream tooling can perform its
    own formatting.

    Args:
        data: Aggregated weekly report data.

    Returns:
        A pretty-printed, sorted-key JSON string.
    """

    def _ticket_dict(t: TicketSummary) -> dict:
        return {
            "ticket_key": t.ticket_key,
            "ticket_type": t.ticket_type,
            "status": t.status,
            "duration_seconds": t.duration_seconds,
            "input_tokens": t.input_tokens,
            "output_tokens": t.output_tokens,
            "ci_cycles": t.ci_cycles,
            "outcome": t.outcome,
            "tokens_by_stage": {
                stage: {"input": in_tok, "output": out_tok}
                for stage, (in_tok, out_tok) in t.tokens_by_stage.items()
            },
            "revision_counts": t.revision_counts,
            "stage_durations": t.stage_durations,
        }

    def _rollup_dict(rollup: FeatureRollup) -> dict:
        return {
            "feature_key": rollup.feature_key,
            "feature_summary": rollup.feature_summary,
            "total_input_tokens": rollup.total_input_tokens,
            "total_output_tokens": rollup.total_output_tokens,
            "total_duration": rollup.total_duration,
            "tickets_completed": rollup.tickets_completed,
            "tickets_in_progress": rollup.tickets_in_progress,
            "completion_percentage": rollup.completion_percentage,
            "linked_tickets": [t.ticket_key for t in rollup.linked_tickets],
        }

    payload: dict = {
        "project": data.project,
        "period_days": data.period_days,
        "report_start": data.report_start,
        "report_end": data.report_end,
        "summary": {
            "total_tickets": len(data.all_tickets),
            "completed": len(data.completed_tickets),
            "in_progress": len(data.in_progress_tickets),
            "blocked": len(data.blocked_tickets),
            "avg_cycle_time_seconds": data.avg_cycle_time,
            "total_input_tokens": data.total_input_tokens,
            "total_output_tokens": data.total_output_tokens,
        },
        "tokens_by_stage": {
            stage: {"input": in_tok, "output": out_tok}
            for stage, (in_tok, out_tok) in data.tokens_by_stage.items()
        },
        "bottlenecks": {
            "total_tickets_analyzed": data.bottlenecks.total_tickets_analyzed,
            "slowest_stage": data.bottlenecks.slowest_stage,
            "ci_fix_rate": data.bottlenecks.ci_fix_rate,
            "most_revised_stages": data.bottlenecks.most_revised_stages,
            "avg_stage_durations": data.bottlenecks.avg_stage_durations,
        },
        "completed_tickets": [_ticket_dict(t) for t in data.completed_tickets],
        "in_progress_tickets": [_ticket_dict(t) for t in data.in_progress_tickets],
        "blocked_tickets": [_ticket_dict(t) for t in data.blocked_tickets],
        "feature_rollups": {
            key: _rollup_dict(rollup) for key, rollup in data.feature_rollups.items()
        },
    }

    return json.dumps(payload, indent=2, sort_keys=True)
