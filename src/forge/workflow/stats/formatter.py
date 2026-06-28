"""Jira wiki markup formatter for workflow statistics summaries.

This module transforms StatsState data into Jira wiki markup suitable for
posting as a comment on the associated Jira ticket at the end of a workflow run.
"""

from forge.workflow.stats import (
    ALL_BUG_STAGES,
    ALL_FEATURE_STAGES,
    StageStats,
    StatsState,
)
from forge.workflow.stats.costing import calculate_stage_cost

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

#: Stage keys that only appear in Bug workflows.
_BUG_ONLY_STAGES = frozenset({"triage", "rca", "planning"})


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


def _fmt_cost(cost: float) -> str:
    """Format a dollar cost value for display (e.g. '$1.23')."""
    return f"${cost:.2f}"


def _build_stage_row(
    label: str,
    stage: StageStats | None,
    pricing: dict[str, dict[str, float]] | None = None,
) -> str:
    """Return a single Jira table row for a workflow stage.

    If *stage* is None (never executed), all metric columns show '—'.

    Args:
        label: Human-readable stage label for the first column.
        stage: Stage metrics dict, or ``None`` when the stage was not executed.
        pricing: Optional LLM pricing table passed to :func:`calculate_stage_cost`.
            When ``None``, the cost column shows ``cost unavailable``.
    """
    if stage is None:
        return f"| {label} | {_DASH} | {_DASH} | {_DASH} | {_DASH} | {_DASH} |"

    iterations = stage.get("iteration_count", 0)
    machine_time = _fmt_seconds(stage.get("machine_time_seconds", 0.0))
    input_tok = _fmt_tokens(stage.get("input_tokens", 0))
    output_tok = _fmt_tokens(stage.get("output_tokens", 0))

    if pricing is not None:
        model_name = stage.get("model_name")
        input_cost, output_cost = calculate_stage_cost(
            model_name,
            stage.get("input_tokens", 0),
            stage.get("output_tokens", 0),
            pricing,
        )
        if input_cost is not None and output_cost is not None:
            cost_str = _fmt_cost(input_cost + output_cost)
        else:
            cost_str = "cost unavailable"
    else:
        cost_str = "cost unavailable"

    return f"| {label} | {iterations} | {machine_time} | {input_tok} | {output_tok} | {cost_str} |"


def _build_totals_row(
    stages: dict[str, StageStats],
    pricing: dict[str, dict[str, float]] | None = None,
) -> str:
    """Return the aggregate token totals row summed across all stages.

    Args:
        stages: Mapping of stage key to stage metrics.
        pricing: Optional LLM pricing table.  When provided, computes and
            displays a total dollar cost.  When ``None`` or any stage has an
            unknown model, shows ``cost unavailable``.
    """
    total_input = sum(s.get("input_tokens", 0) for s in stages.values())
    total_output = sum(s.get("output_tokens", 0) for s in stages.values())

    cost_str = _build_total_cost_str(stages, pricing)

    return (
        f"| *Total* | — | — |"
        f" *{_fmt_tokens(total_input)}* | *{_fmt_tokens(total_output)}* | {cost_str} |"
    )


def _build_total_cost_str(
    stages: dict[str, StageStats],
    pricing: dict[str, dict[str, float]] | None,
) -> str:
    """Compute the formatted total cost string for the totals row.

    Returns ``'cost unavailable'`` when *pricing* is ``None`` or any stage
    with recorded tokens has an unknown model.  Otherwise returns a formatted
    dollar amount.
    """
    if pricing is None:
        return "cost unavailable"

    total_cost = 0.0
    for stage in stages.values():
        model_name = stage.get("model_name")
        input_tokens = stage.get("input_tokens", 0)
        output_tokens = stage.get("output_tokens", 0)
        if input_tokens == 0 and output_tokens == 0:
            # Stage used no tokens — skip without penalising the total.
            continue
        input_cost, output_cost = calculate_stage_cost(
            model_name, input_tokens, output_tokens, pricing
        )
        if input_cost is None or output_cost is None:
            return "cost unavailable"
        total_cost += input_cost + output_cost

    return _fmt_cost(total_cost)


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


def _build_cost_alert(
    total_tokens: int,
    threshold: int,
) -> list[str]:
    """Return Jira wiki markup lines for a token-based cost alert section.

    The alert is displayed as a visually prominent panel when the aggregate
    token usage exceeds *threshold*.

    Args:
        total_tokens: Actual aggregate token count (input + output).
        threshold: Configured token threshold that was exceeded.

    Returns:
        A list of Jira wiki markup lines (without a trailing newline).
    """
    return [
        "",
        "{panel:title=⚠️ COST ALERT|borderColor=#FF0000|titleBGColor=#FF0000|titleColor=#FFFFFF|bgColor=#FFF0F0}",
        "Token usage has exceeded the configured threshold.",
        f"*Threshold:* {_fmt_tokens(threshold)} tokens",
        f"*Actual usage:* {_fmt_tokens(total_tokens)} tokens",
        "{panel}",
    ]


def _build_dollar_cost_alert(
    total_cost: float,
    threshold: float,
) -> list[str]:
    """Return Jira wiki markup lines for a dollar-based cost alert section.

    The alert is displayed as a visually prominent panel when the aggregate
    dollar cost exceeds *threshold*.

    Args:
        total_cost: Actual aggregate dollar cost across all stages.
        threshold: Configured dollar threshold that was exceeded.

    Returns:
        A list of Jira wiki markup lines (without a trailing newline).
    """
    return [
        "",
        "{panel:title=⚠️ COST ALERT|borderColor=#FF0000|titleBGColor=#FF0000|titleColor=#FFFFFF|bgColor=#FFF0F0}",
        "LLM cost has exceeded the configured threshold.",
        f"*Threshold:* {_fmt_cost(threshold)}",
        f"*Actual cost:* {_fmt_cost(total_cost)}",
        "{panel}",
    ]


def format_stats_summary(
    stats: StatsState,
    outcome: str,
    outcome_detail: str | None = None,
    token_threshold: int | None = None,
    dollar_threshold: float | None = None,
    pricing: dict[str, dict[str, float]] | None = None,
) -> str:
    """Format a StatsState snapshot into a Jira wiki markup comment.

    The generated comment includes:
    * A stage-by-stage metrics table (iterations, machine time,
      input tokens, output tokens, cost).
    * An aggregate token totals row with total cost.
    * A PR links section (omitted when no PRs were created).
    * A CI cycles line.
    * A final outcome field.
    * An optional cost alert panel when total token usage exceeds
      *token_threshold* or total dollar cost exceeds *dollar_threshold*
      (omitted when both thresholds are ``None`` or not exceeded).

    When *dollar_threshold* is set it takes precedence over *token_threshold*
    for cost alerting purposes.

    Args:
        stats: The workflow statistics state to format.
        outcome: Outcome category — one of ``"completed"``, ``"blocked"``, or
            ``"failed"`` (matched case-insensitively).
        outcome_detail: Optional elaboration on the outcome (e.g. the blocking
            reason or error message).  Truncated to 200 characters if longer.
        token_threshold: Optional token count threshold.  When the aggregate
            token usage (input + output across all stages) exceeds this value,
            a prominent "⚠️ COST ALERT" section is appended to the summary.
            Pass ``None`` (the default) to disable token-based cost alerting.
        dollar_threshold: Optional dollar cost threshold.  When set, compares
            total dollar cost against this value rather than using the token
            threshold.  Pass ``None`` (the default) to use token-based alerting.
        pricing: Optional LLM pricing table (mapping model name substrings to
            ``{"input": $/MTok, "output": $/MTok}``).  When provided, a *Cost*
            column is populated in the stage table.  Defaults to ``None``.

    Returns:
        A Jira wiki markup string ready to post as a ticket comment.
    """
    stages: dict[str, StageStats] = stats.get("stage_timestamps") or {}
    pr_urls: list[str] = stats.get("stats_pr_urls") or []
    ci_cycles: int = stats.get("stats_ci_cycles") or 0

    lines: list[str] = []

    # ------------------------------------------------------------------
    # Stage metrics table
    # ------------------------------------------------------------------
    lines.append("h3. Workflow Statistics")
    lines.append("")
    lines.append(
        "|| Stage || Iterations || Machine Time || Input Tokens || Output Tokens || Cost ||"
    )

    # Detect workflow type: prefer bug stage ordering when any bug-only stage
    # key is present in the recorded data.
    display_stages = (
        ALL_BUG_STAGES if any(k in stages for k in _BUG_ONLY_STAGES) else ALL_FEATURE_STAGES
    )
    for stage_key in display_stages:
        label = _STAGE_LABELS.get(stage_key, stage_key.title())
        stage_data = stages.get(stage_key)
        lines.append(_build_stage_row(label, stage_data, pricing=pricing))

    # Aggregate totals row (always shown, even when no stages ran)
    lines.append(_build_totals_row(stages, pricing=pricing))

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

    # ------------------------------------------------------------------
    # Cost alert (only when threshold is configured and exceeded)
    # ------------------------------------------------------------------
    if dollar_threshold is not None and pricing is not None:
        # Dollar-based alerting takes precedence over token-based.
        total_cost_str = _build_total_cost_str(stages, pricing)
        # Only alert when total cost is computable (not 'cost unavailable').
        if total_cost_str != "cost unavailable":
            total_cost = float(total_cost_str.lstrip("$"))
            if total_cost > dollar_threshold:
                lines.extend(_build_dollar_cost_alert(total_cost, dollar_threshold))
    elif token_threshold is not None:
        total_tokens = sum(
            s.get("input_tokens", 0) + s.get("output_tokens", 0) for s in stages.values()
        )
        if total_tokens > token_threshold:
            lines.extend(_build_cost_alert(total_tokens, token_threshold))

    return "\n".join(lines)
