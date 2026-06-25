"""Weekly report data aggregation module.

Collects and aggregates workflow statistics from Redis checkpoints to produce
a summary of activity over a configurable time window (default: 7 days).

Usage::

    from forge.workflow.stats.weekly_report import collect_weekly_data

    report = await collect_weekly_data("AISOS", days=7)
    print(f"Completed: {report.completed_tickets}")
    print(f"In Progress: {report.in_progress_tickets}")
    print(f"Blocked: {report.blocked_tickets}")
    print(f"Avg Cycle Time: {report.avg_cycle_time:.1f}s")
"""

from __future__ import annotations

import contextlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from forge.integrations.jira.client import JiraClient
from forge.orchestrator.checkpointer import get_redis_client

#: Sentinel key used to group tickets that could not be linked to any Feature.
UNASSIGNED_FEATURE_KEY = "Unassigned"

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis key pattern used by langgraph-checkpoint-redis
# ---------------------------------------------------------------------------

#: Prefix used by langgraph-checkpoint-redis for checkpoint storage.
_CHECKPOINT_KEY_PREFIX = "langgraph:checkpoint:"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TicketSummary:
    """Per-ticket statistics extracted from a workflow checkpoint.

    Attributes:
        ticket_key: The Jira issue key (e.g. ``"AISOS-123"``).
        ticket_type: Workflow type — ``"Feature"`` or ``"Bug"``.
        status: Derived status — one of ``"completed"``, ``"in_progress"``,
            or ``"blocked"``.
        duration_seconds: Wall-clock seconds from the first stage start to
            workflow completion, or to *now* when still in progress.  ``None``
            when no stage timing is available.
        input_tokens: Total LLM prompt tokens consumed across all stages.
        output_tokens: Total LLM completion tokens consumed across all stages.
        tokens_by_stage: Per-stage token totals as ``{stage_name: (in, out)}``.
        revision_counts: Per-stage iteration count as ``{stage_name: count}``.
        ci_cycles: Number of CI fix-attempt cycles triggered during the run.
        outcome: The raw ``stats_outcome`` string from the checkpoint, or
            ``None`` when the workflow is still in progress.
        stage_durations: Per-stage machine time in seconds ``{stage_name: secs}``.
    """

    ticket_key: str
    ticket_type: str = "Feature"
    status: str = "in_progress"
    duration_seconds: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    tokens_by_stage: dict[str, tuple[int, int]] = field(default_factory=dict)
    revision_counts: dict[str, int] = field(default_factory=dict)
    ci_cycles: int = 0
    outcome: str | None = None
    stage_durations: dict[str, float] = field(default_factory=dict)


@dataclass
class BottleneckAnalysis:
    """Stage-level performance metrics computed across a set of tickets.

    Attributes:
        avg_stage_durations: Average machine time per stage across all tickets
            that executed that stage, in seconds.  ``{stage_name: avg_seconds}``.
        most_revised_stages: Stage names ordered by average iteration count
            (descending).  The first element is the most-revised stage.
        ci_fix_rate: Fraction of tickets (0.0–1.0) that triggered at least one
            CI fix cycle.  ``0.0`` when no tickets are present.
        slowest_stage: The stage with the highest average duration, or ``None``
            when no stage data is available.
        total_tickets_analyzed: Number of tickets used to compute these metrics.
    """

    avg_stage_durations: dict[str, float] = field(default_factory=dict)
    most_revised_stages: list[str] = field(default_factory=list)
    ci_fix_rate: float = 0.0
    slowest_stage: str | None = None
    total_tickets_analyzed: int = 0


@dataclass
class FeatureRollup:
    """Aggregated statistics for all tickets linked to a single Feature.

    Tickets may be linked to the Feature directly (when their parent is the
    Feature itself) or indirectly (when their parent is an Epic whose parent
    is the Feature).

    Attributes:
        feature_key: The Jira key of the parent Feature (e.g. ``"AISOS-10"``),
            or the ``UNASSIGNED_FEATURE_KEY`` sentinel for tickets that could
            not be resolved to any Feature.
        feature_summary: The summary/title of the Feature issue, or an empty
            string when the Feature could not be fetched (e.g. network error).
        linked_tickets: All :class:`TicketSummary` objects grouped under this
            Feature.
        total_input_tokens: Sum of prompt tokens across all linked tickets.
        total_output_tokens: Sum of completion tokens across all linked tickets.
        total_duration: Sum of ``duration_seconds`` across all linked tickets
            that have timing data.  ``None`` when no ticket has timing data.
        tickets_completed: Number of linked tickets with status ``"completed"``.
        tickets_in_progress: Number of linked tickets with status
            ``"in_progress"``.
        completion_percentage: Fraction of linked tickets that are completed,
            expressed as a value in ``[0.0, 100.0]``.  ``0.0`` when there are
            no linked tickets.
    """

    feature_key: str
    feature_summary: str = ""
    linked_tickets: list[TicketSummary] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_duration: float | None = None
    tickets_completed: int = 0
    tickets_in_progress: int = 0
    completion_percentage: float = 0.0


@dataclass
class WeeklyReportData:
    """Aggregated weekly report data across all matching workflow checkpoints.

    Attributes:
        project: The Jira project key used to filter checkpoints.
        period_days: Number of days covered by the report window.
        report_start: ISO-8601 UTC timestamp marking the start of the window.
        report_end: ISO-8601 UTC timestamp marking the end of the window (now).
        completed_tickets: Tickets whose workflow completed successfully during
            the window.
        in_progress_tickets: Tickets still actively running during the window.
        blocked_tickets: Tickets that are currently blocked.
        total_input_tokens: Sum of all prompt tokens across every ticket.
        total_output_tokens: Sum of all completion tokens across every ticket.
        tokens_by_stage: Aggregate token totals per stage
            ``{stage_name: (total_in, total_out)}``.
        avg_cycle_time: Average duration in seconds from first stage start to
            workflow completion, computed over completed tickets only.  ``None``
            when no completed tickets have timing data.
        bottlenecks: Stage-level performance metrics for the entire period.
        all_tickets: All ``TicketSummary`` objects included in this report.
    """

    project: str
    period_days: int = 7
    report_start: str = ""
    report_end: str = ""
    completed_tickets: list[TicketSummary] = field(default_factory=list)
    in_progress_tickets: list[TicketSummary] = field(default_factory=list)
    blocked_tickets: list[TicketSummary] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    tokens_by_stage: dict[str, tuple[int, int]] = field(default_factory=dict)
    avg_cycle_time: float | None = None
    bottlenecks: BottleneckAnalysis = field(default_factory=BottleneckAnalysis)
    all_tickets: list[TicketSummary] = field(default_factory=list)
    feature_rollups: dict[str, FeatureRollup] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_timestamp(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp string into an aware UTC datetime.

    Args:
        ts: ISO-8601 timestamp string (e.g. ``"2024-01-01T12:00:00+00:00"``),
            or ``None``.

    Returns:
        An aware :class:`datetime` in UTC, or ``None`` when *ts* is absent or
        unparseable.
    """
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        # Ensure the datetime is timezone-aware (convert naive to UTC)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        logger.debug("Could not parse timestamp %r", ts)
        return None


def _parse_checkpoint_stats(state: dict) -> TicketSummary | None:
    """Extract a :class:`TicketSummary` from a single checkpoint state dict.

    Reads the ``stage_timestamps``, ``stats_ci_cycles``, ``workflow_outcome``,
    ``ticket_key``, and ``ticket_type`` fields produced by the stats
    recording utilities.

    Args:
        state: Raw checkpoint state dict as returned by the checkpoint reader.

    Returns:
        A populated :class:`TicketSummary`, or ``None`` when the state lacks
        the minimum required fields (``ticket_key``, ``stage_timestamps``).
    """
    ticket_key: str | None = state.get("ticket_key")
    if not ticket_key:
        logger.debug("Checkpoint state missing ticket_key; skipping")
        return None

    if "stage_timestamps" not in state:
        logger.debug("Checkpoint for %s has no stage_timestamps; skipping", ticket_key)
        return None

    stats_stages: dict = state.get("stage_timestamps") or {}
    if not isinstance(stats_stages, dict):
        logger.warning(
            "Malformed stage_timestamps for %s (type %s); treating as empty",
            ticket_key,
            type(stats_stages).__name__,
        )
        stats_stages = {}

    # --- Ticket type ---
    raw_type = state.get("ticket_type", "")
    ticket_type = str(raw_type) if raw_type else "Feature"

    # --- Outcome / status ---
    outcome: str | None = state.get("workflow_outcome")
    is_blocked: bool = bool(state.get("is_blocked", False))

    if outcome and outcome.lower().startswith("completed"):
        status = "completed"
    elif is_blocked or (outcome and outcome.lower().startswith("blocked")):
        status = "blocked"
    else:
        status = "in_progress"

    # --- Token aggregation ---
    input_tokens = 0
    output_tokens = 0
    tokens_by_stage: dict[str, tuple[int, int]] = {}
    revision_counts: dict[str, int] = {}
    stage_durations: dict[str, float] = {}

    for stage_name, stage_data in stats_stages.items():
        if not isinstance(stage_data, dict):
            continue
        stage_in = int(stage_data.get("input_tokens", 0) or 0)
        stage_out = int(stage_data.get("output_tokens", 0) or 0)
        input_tokens += stage_in
        output_tokens += stage_out
        tokens_by_stage[stage_name] = (stage_in, stage_out)
        revision_counts[stage_name] = int(stage_data.get("iteration_count", 0) or 0)
        machine_time = float(stage_data.get("machine_time_seconds", 0.0) or 0.0)
        stage_durations[stage_name] = machine_time

    # --- Cycle time: first stage start → last stage end (or now) ---
    duration_seconds: float | None = None

    start_times = []
    end_times = []
    for stage_data in stats_stages.values():
        if not isinstance(stage_data, dict):
            continue
        started = _parse_timestamp(stage_data.get("started_at"))
        ended = _parse_timestamp(stage_data.get("ended_at"))
        if started:
            start_times.append(started)
        if ended:
            end_times.append(ended)

    if start_times:
        earliest_start = min(start_times)
        if status == "completed" and end_times:
            latest_end = max(end_times)
            duration_seconds = (latest_end - earliest_start).total_seconds()
        elif status != "completed":
            # Still in-progress: measure up to now
            duration_seconds = (datetime.now(UTC) - earliest_start).total_seconds()

    ci_cycles = int(state.get("stats_ci_cycles", 0) or 0)

    return TicketSummary(
        ticket_key=ticket_key,
        ticket_type=ticket_type,
        status=status,
        duration_seconds=duration_seconds,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tokens_by_stage=tokens_by_stage,
        revision_counts=revision_counts,
        ci_cycles=ci_cycles,
        outcome=outcome,
        stage_durations=stage_durations,
    )


def _calculate_bottlenecks(tickets: list[TicketSummary]) -> BottleneckAnalysis:
    """Compute stage-level performance metrics from a collection of tickets.

    For each stage that appears in at least one ticket, the following are
    computed:

    * **avg_stage_durations** — mean machine time in seconds across tickets
      that executed the stage.
    * **most_revised_stages** — stages ordered by mean iteration count
      (descending); stages with equal counts preserve insertion order.
    * **ci_fix_rate** — fraction of tickets that triggered ≥ 1 CI cycle.
    * **slowest_stage** — stage name with the highest average duration.

    Args:
        tickets: The list of :class:`TicketSummary` objects to analyse.

    Returns:
        A populated :class:`BottleneckAnalysis`.
    """
    if not tickets:
        return BottleneckAnalysis(total_tickets_analyzed=0)

    # Accumulate stage durations and revision counts across all tickets
    stage_duration_totals: dict[str, float] = {}
    stage_duration_counts: dict[str, int] = {}
    stage_revision_totals: dict[str, int] = {}
    stage_revision_counts: dict[str, int] = {}

    ci_triggered = 0

    for ticket in tickets:
        if ticket.ci_cycles > 0:
            ci_triggered += 1

        for stage_name, duration in ticket.stage_durations.items():
            stage_duration_totals[stage_name] = (
                stage_duration_totals.get(stage_name, 0.0) + duration
            )
            stage_duration_counts[stage_name] = stage_duration_counts.get(stage_name, 0) + 1

        for stage_name, rev_count in ticket.revision_counts.items():
            stage_revision_totals[stage_name] = stage_revision_totals.get(stage_name, 0) + rev_count
            stage_revision_counts[stage_name] = stage_revision_counts.get(stage_name, 0) + 1

    # Compute averages
    avg_stage_durations: dict[str, float] = {
        stage: stage_duration_totals[stage] / stage_duration_counts[stage]
        for stage in stage_duration_totals
    }

    avg_revision_counts: dict[str, float] = {
        stage: stage_revision_totals[stage] / stage_revision_counts[stage]
        for stage in stage_revision_totals
    }

    # Order stages by mean revision count descending
    most_revised_stages = sorted(
        avg_revision_counts.keys(),
        key=lambda s: avg_revision_counts[s],
        reverse=True,
    )

    # CI fix rate
    ci_fix_rate = ci_triggered / len(tickets)

    # Slowest stage by average duration
    slowest_stage: str | None = None
    if avg_stage_durations:
        slowest_stage = max(avg_stage_durations, key=lambda s: avg_stage_durations[s])

    return BottleneckAnalysis(
        avg_stage_durations=avg_stage_durations,
        most_revised_stages=most_revised_stages,
        ci_fix_rate=ci_fix_rate,
        slowest_stage=slowest_stage,
        total_tickets_analyzed=len(tickets),
    )


def _is_within_window(state: dict, cutoff: datetime) -> bool:
    """Return True if the checkpoint falls within the reporting time window.

    A checkpoint is considered *within the window* when any of the following
    conditions hold:

    1. The ``updated_at`` timestamp is ≥ *cutoff*.
    2. Any ``started_at`` or ``ended_at`` timestamp in ``stats_stages`` is
       ≥ *cutoff*.

    Args:
        state: Raw checkpoint state dict.
        cutoff: The earliest datetime (inclusive) to include.

    Returns:
        ``True`` if the checkpoint falls within the window.
    """
    updated_at = _parse_timestamp(state.get("updated_at"))
    if updated_at and updated_at >= cutoff:
        return True

    stats_stages = state.get("stage_timestamps") or {}
    if not isinstance(stats_stages, dict):
        return False

    for stage_data in stats_stages.values():
        if not isinstance(stage_data, dict):
            continue
        for ts_key in ("started_at", "ended_at"):
            ts = _parse_timestamp(stage_data.get(ts_key))
            if ts and ts >= cutoff:
                return True

    return False


def _aggregate_tokens(
    tickets: list[TicketSummary],
) -> tuple[int, int, dict[str, tuple[int, int]]]:
    """Sum token counts across all tickets.

    Args:
        tickets: The ticket summaries to aggregate.

    Returns:
        A 3-tuple of ``(total_input, total_output, tokens_by_stage)`` where
        *tokens_by_stage* maps stage name to ``(total_in, total_out)`` across
        all tickets.
    """
    total_in = 0
    total_out = 0
    by_stage: dict[str, list[int]] = {}  # stage -> [total_in, total_out]

    for ticket in tickets:
        total_in += ticket.input_tokens
        total_out += ticket.output_tokens
        for stage_name, (s_in, s_out) in ticket.tokens_by_stage.items():
            if stage_name not in by_stage:
                by_stage[stage_name] = [0, 0]
            by_stage[stage_name][0] += s_in
            by_stage[stage_name][1] += s_out

    tokens_by_stage: dict[str, tuple[int, int]] = {
        stage: (totals[0], totals[1]) for stage, totals in by_stage.items()
    }
    return total_in, total_out, tokens_by_stage


def _avg_cycle_time(tickets: list[TicketSummary]) -> float | None:
    """Compute the average cycle time for completed tickets.

    Only completed tickets with non-None ``duration_seconds`` are included.

    Args:
        tickets: All ticket summaries (not just completed ones).

    Returns:
        Average cycle time in seconds, or ``None`` when no applicable tickets
        are found.
    """
    durations = [
        t.duration_seconds
        for t in tickets
        if t.status == "completed" and t.duration_seconds is not None
    ]
    if not durations:
        return None
    return sum(durations) / len(durations)


# ---------------------------------------------------------------------------
# Feature rollup helpers
# ---------------------------------------------------------------------------


async def _resolve_feature_key(
    ticket: TicketSummary,
    jira: JiraClient,
) -> str | None:
    """Resolve the parent Feature key for a ticket by traversing the hierarchy.

    The lookup strategy is:

    1. Fetch the Jira issue for *ticket.ticket_key*.
    2. If its ``issue_type`` is ``"Feature"``, return its own key (the ticket
       *is* the Feature).
    3. If it has a parent, fetch the parent.
    4. If the parent ``issue_type`` is ``"Feature"``, return the parent key
       (ticket is directly under a Feature).
    5. If the parent is an ``"Epic"``, fetch *its* parent and return that key
       when the grandparent is a ``"Feature"``.
    6. Return ``None`` when no Feature ancestor is found within two hops, or
       when any Jira API call fails.

    Args:
        ticket: The ticket whose Feature ancestry should be resolved.
        jira: An open :class:`JiraClient` to use for API calls.

    Returns:
        The Jira key of the nearest Feature ancestor, or ``None`` when
        resolution fails or no Feature is found.
    """
    with contextlib.suppress(Exception):
        issue = await jira.get_issue(ticket.ticket_key)

        # The ticket itself is a Feature (unusual but possible)
        if issue.issue_type == "Feature":
            return issue.key

        if not issue.parent_key:
            return None

        parent = await jira.get_issue(issue.parent_key)

        if parent.issue_type == "Feature":
            return parent.key

        # Parent is an Epic — climb one more level to find the Feature
        if parent.issue_type == "Epic" and parent.parent_key:
            grandparent = await jira.get_issue(parent.parent_key)
            if grandparent.issue_type == "Feature":
                return grandparent.key

    return None


def _build_feature_rollup(
    feature_key: str,
    feature_summary: str,
    tickets: list[TicketSummary],
) -> FeatureRollup:
    """Build a :class:`FeatureRollup` from a pre-grouped list of tickets.

    Args:
        feature_key: The Feature key (or ``UNASSIGNED_FEATURE_KEY``).
        feature_summary: Human-readable summary of the Feature issue.
        tickets: All tickets that belong to this Feature.

    Returns:
        A fully populated :class:`FeatureRollup`.
    """
    total_in = sum(t.input_tokens for t in tickets)
    total_out = sum(t.output_tokens for t in tickets)

    durations = [t.duration_seconds for t in tickets if t.duration_seconds is not None]
    total_duration: float | None = sum(durations) if durations else None

    tickets_completed = sum(1 for t in tickets if t.status == "completed")
    tickets_in_progress = sum(1 for t in tickets if t.status == "in_progress")

    completion_pct = (tickets_completed / len(tickets) * 100.0) if tickets else 0.0

    return FeatureRollup(
        feature_key=feature_key,
        feature_summary=feature_summary,
        linked_tickets=list(tickets),
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        total_duration=total_duration,
        tickets_completed=tickets_completed,
        tickets_in_progress=tickets_in_progress,
        completion_percentage=completion_pct,
    )


async def _group_by_feature(
    tickets: list[TicketSummary],
    jira: JiraClient,
) -> dict[str, FeatureRollup]:
    """Group tickets by their parent Feature and return per-Feature rollups.

    For each ticket:

    * If the ticket can be resolved to a Feature via the Jira hierarchy,
      it is placed in that Feature's rollup.
    * Otherwise it is placed under the ``UNASSIGNED_FEATURE_KEY`` sentinel.

    Feature summaries are fetched from Jira for each resolved Feature key.
    The ``UNASSIGNED_FEATURE_KEY`` group always has an empty ``feature_summary``.

    Args:
        tickets: The ticket summaries to group.
        jira: An open :class:`JiraClient` used for hierarchy resolution.

    Returns:
        A dict mapping Feature key (or ``UNASSIGNED_FEATURE_KEY``) to a
        :class:`FeatureRollup`.  Returns an empty dict when *tickets* is empty.
    """
    if not tickets:
        return {}

    # Map each ticket to its resolved feature key (or None → Unassigned)
    groups: dict[str, list[TicketSummary]] = {}
    feature_summaries: dict[str, str] = {}

    for ticket in tickets:
        feature_key = await _resolve_feature_key(ticket, jira)
        bucket = feature_key if feature_key is not None else UNASSIGNED_FEATURE_KEY
        groups.setdefault(bucket, []).append(ticket)

        # Fetch the Feature summary once per unique key
        if feature_key is not None and feature_key not in feature_summaries:
            with contextlib.suppress(Exception):
                feature_issue = await jira.get_issue(feature_key)
                feature_summaries[feature_key] = feature_issue.summary

    result: dict[str, FeatureRollup] = {}
    for bucket_key, bucket_tickets in groups.items():
        summary = feature_summaries.get(bucket_key, "")
        result[bucket_key] = _build_feature_rollup(bucket_key, summary, bucket_tickets)

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def collect_weekly_data(
    project: str,
    days: int = 7,
    *,
    jira_client: JiraClient | None = None,
) -> WeeklyReportData:
    """Collect and aggregate workflow statistics for a project over a time window.

    Scans all Redis keys matching ``langgraph:checkpoint:{project}-*``, reads
    each checkpoint's serialised state, filters to entries whose activity falls
    within the last *days* days, and aggregates the results into a
    :class:`WeeklyReportData`.

    Args:
        project: The Jira project key to filter checkpoints (e.g. ``"AISOS"``).
            The scan pattern is ``langgraph:checkpoint:{project}-*``.
        days: Number of days to look back from *now* (default: 7).
        jira_client: Optional :class:`JiraClient` instance to use for Feature
            hierarchy resolution.  When ``None`` a new client is created and
            closed automatically.  Pass an explicit client in tests to avoid
            real HTTP calls.

    Returns:
        A fully populated :class:`WeeklyReportData`.  If no matching
        checkpoints exist, the report contains zero-value aggregates.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    report_end = now.isoformat()
    report_start = cutoff.isoformat()

    pattern = f"{_CHECKPOINT_KEY_PREFIX}{project}-*"
    logger.info(
        "Collecting weekly report for project=%s, days=%d, pattern=%s",
        project,
        days,
        pattern,
    )

    redis_client = await get_redis_client()
    all_tickets: list[TicketSummary] = []

    try:
        cursor = 0
        scanned_keys: list[str] = []

        while True:
            cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=100)
            scanned_keys.extend(keys)
            if cursor == 0:
                break

        logger.debug("Found %d checkpoint keys for project=%s", len(scanned_keys), project)

        for key in scanned_keys:
            try:
                raw = await redis_client.get(key)
                if raw is None:
                    continue
                state = json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(state, dict):
                    logger.debug("Unexpected checkpoint value type at key %s; skipping", key)
                    continue

                # Filter by time window
                if not _is_within_window(state, cutoff):
                    logger.debug("Checkpoint %s outside reporting window; skipping", key)
                    continue

                ticket = _parse_checkpoint_stats(state)
                if ticket is not None:
                    all_tickets.append(ticket)

            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                logger.warning("Could not parse checkpoint at key %s: %s", key, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Unexpected error reading checkpoint at key %s: %s", key, exc)

    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to scan Redis for project=%s: %s", project, exc)

    # --- Categorise tickets ---
    completed = [t for t in all_tickets if t.status == "completed"]
    in_progress = [t for t in all_tickets if t.status == "in_progress"]
    blocked = [t for t in all_tickets if t.status == "blocked"]

    # --- Aggregate tokens ---
    total_in, total_out, tokens_by_stage = _aggregate_tokens(all_tickets)

    # --- Average cycle time (completed tickets only) ---
    avg_ct = _avg_cycle_time(all_tickets)

    # --- Bottleneck analysis ---
    bottlenecks = _calculate_bottlenecks(all_tickets)

    # --- Per-Feature rollup ---
    _owns_jira_client = jira_client is None
    if _owns_jira_client:
        jira_client = JiraClient()
    try:
        feature_rollups = await _group_by_feature(all_tickets, jira_client)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to build feature rollups: %s", exc)
        feature_rollups = {}
    finally:
        if _owns_jira_client:
            await jira_client.close()  # type: ignore[union-attr]

    report = WeeklyReportData(
        project=project,
        period_days=days,
        report_start=report_start,
        report_end=report_end,
        completed_tickets=completed,
        in_progress_tickets=in_progress,
        blocked_tickets=blocked,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        tokens_by_stage=tokens_by_stage,
        avg_cycle_time=avg_ct,
        bottlenecks=bottlenecks,
        all_tickets=all_tickets,
        feature_rollups=feature_rollups,
    )

    logger.info(
        "Weekly report for project=%s: completed=%d, in_progress=%d, blocked=%d, total_tokens=%d",
        project,
        len(completed),
        len(in_progress),
        len(blocked),
        total_in + total_out,
    )

    return report


__all__ = [
    "BottleneckAnalysis",
    "FeatureRollup",
    "TicketSummary",
    "UNASSIGNED_FEATURE_KEY",
    "WeeklyReportData",
    "collect_weekly_data",
]
