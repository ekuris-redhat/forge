"""Weekly status reporting, formatting engine and idempotent publishing logic."""

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    """Token consumption metrics."""

    input: int = Field(default=0, description="Total input tokens")
    output: int = Field(default=0, description="Total output tokens")
    total: int = Field(default=0, description="Total tokens combined")


class TicketMetrics(BaseModel):
    """Workflow metrics for a specific ticket."""

    ticket_key: str = Field(..., description="The Jira ticket key")
    durations: dict[str, float] = Field(
        default_factory=dict, description="Phase-level durations in seconds"
    )
    token_usage: TokenUsage = Field(
        default_factory=TokenUsage, description="Token usage for this ticket"
    )
    cost: float = Field(default=0.0, description="Total cost of processing this ticket in USD")


class WeeklyReportMetrics(BaseModel):
    """Aggregated workflow metrics for a project over a reporting period."""

    project_key: str = Field(..., description="The Jira project key")
    window_days: int = Field(..., description="The rolling window size in days")
    start_time: str = Field(..., description="The start time of the reporting window in ISO format")
    end_time: str = Field(..., description="The end time of the reporting window in ISO format")
    active_tickets: list[str] = Field(
        default_factory=list, description="Keys of active tickets in the window"
    )
    total_duration_seconds: float = Field(
        default=0.0, description="Total duration spent on all tickets in seconds"
    )
    phase_durations: dict[str, float] = Field(
        default_factory=dict, description="Total durations spent on each phase in seconds"
    )
    token_usage: TokenUsage = Field(
        default_factory=TokenUsage, description="Total token consumption"
    )
    total_cost: float = Field(default=0.0, description="Total cost in USD")
    tickets: dict[str, TicketMetrics] = Field(
        default_factory=dict, description="Per-ticket metrics breakdown"
    )

    def to_json(self) -> str:
        """Serialize the report metrics to JSON with correct schema validation."""
        # model_dump_json() ensures Pydantic validation and correct serialization
        return self.model_dump_json(indent=2)

    def to_markdown(self) -> str:
        """Generate a structured markdown summary report."""
        lines = []
        lines.append(f"# Weekly Status Report: {self.project_key}")
        lines.append("")
        lines.append(
            f"**Reporting Period:** {self.start_time} to {self.end_time} ({self.window_days} days)"
        )
        lines.append(f"**Active Tickets:** {len(self.active_tickets)}")
        lines.append("")

        lines.append("## Summary Metrics")
        lines.append(f"- **Total Cost:** ${self.total_cost:.4f} USD")
        lines.append(f"- **Total Duration:** {format_duration(self.total_duration_seconds)}")
        lines.append(
            f"- **Total Token Usage:** {self.token_usage.input:,} input / "
            f"{self.token_usage.output:,} output ({self.token_usage.total:,} total)"
        )
        lines.append("")

        lines.append("## Phase Breakdowns")
        if self.phase_durations:
            lines.append("| Phase | Duration |")
            lines.append("| :--- | :--- |")
            for phase, duration in sorted(self.phase_durations.items()):
                lines.append(f"| {phase} | {format_duration(duration)} |")
        else:
            lines.append("*No phase activity recorded.*")
        lines.append("")

        lines.append("## Checkpoint Breakdowns (Per-Ticket)")
        if self.tickets:
            for ticket_key, t_metrics in sorted(self.tickets.items()):
                lines.append(f"### Ticket: {ticket_key}")
                lines.append(f"- **Cost:** ${t_metrics.cost:.4f} USD")
                ticket_total_dur = sum(t_metrics.durations.values())
                lines.append(f"- **Total Duration:** {format_duration(ticket_total_dur)}")
                lines.append(
                    f"- **Token Usage:** {t_metrics.token_usage.input:,} input / "
                    f"{t_metrics.token_usage.output:,} output ({t_metrics.token_usage.total:,} total)"
                )
                lines.append("")
                lines.append("#### Stage Durations")
                if t_metrics.durations:
                    lines.append("| Stage | Duration |")
                    lines.append("| :--- | :--- |")
                    for stage, duration in sorted(t_metrics.durations.items()):
                        lines.append(f"| {stage} | {format_duration(duration)} |")
                else:
                    lines.append("*No stage durations recorded.*")
                lines.append("")
        else:
            lines.append("*No individual ticket details available.*")

        return "\n".join(lines).strip()


def format_duration(seconds: float) -> str:
    """Format duration in seconds to a human-readable string."""
    if seconds <= 0:
        return "0s"
    parts = []
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    rem_seconds = int(seconds % 60)
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if rem_seconds > 0 or not parts:
        parts.append(f"{rem_seconds}s")
    return " ".join(parts)


def publish_report_idempotently(
    file_path: str, report_markdown: str, start_time: str, end_time: str
) -> None:
    """Writes or updates the weekly markdown report idempotently in the target file.

    If the file already exists, it checks if a report section for the specified
    timeframe exists (defined by start/end comments), updates it, or appends/prepends
    it. If the file does not exist, it creates it.
    """
    # Ensure parent directory exists
    dir_name = os.path.dirname(os.path.abspath(file_path))
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    start_marker = f"<!-- FORGE-WEEKLY-REPORT-START: {start_time} TO {end_time} -->"
    end_marker = "<!-- FORGE-WEEKLY-REPORT-END -->"
    full_report = f"{start_marker}\n{report_markdown}\n{end_marker}"

    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(full_report)
        return

    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    # Look for matching markers to perform idempotent replacement
    if start_marker in content and end_marker in content:
        start_idx = content.find(start_marker)
        end_idx = content.find(end_marker, start_idx)
        if start_idx != -1 and end_idx != -1:
            actual_end_idx = end_idx + len(end_marker)
            new_content = content[:start_idx] + full_report + content[actual_end_idx:]
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            return

    # If the report for this week is new but file already has content, prepend it
    new_content = f"{full_report}\n\n{content}" if content.strip() else full_report

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)


async def generate_weekly_report(
    project_key: str,
    days: int = 7,
    end_time: datetime | None = None,
    jira_client: Any | None = None,
    checkpointer: Any | None = None,
    rate_model: Any | None = None,
) -> WeeklyReportMetrics:
    """Generates an aggregated weekly report for a given project.

    1. Scans checkpoints in Redis to find unique thread/ticket keys.
    2. Filters keys belonging to the specified project (e.g., PROJ-).
    3. Identifies which of these tickets had activity during the reporting window.
    4. Aggregates metrics (durations, tokens, cost) across those active tickets.
    5. Returns a validated WeeklyReportMetrics Pydantic model.
    """
    from forge.integrations.jira.client import JiraClient
    from forge.orchestrator.checkpointer import get_checkpointer, list_checkpoints
    from forge.workflow.stats.aggregator import StateAggregator, to_utc

    end_time = datetime.now(UTC) if end_time is None else to_utc(end_time)

    start_time = end_time - timedelta(days=days)

    # Initialize clients if not provided
    close_jira = False
    if jira_client is None:
        jira_client = JiraClient()
        close_jira = True

    if checkpointer is None:
        checkpointer = await get_checkpointer()

    state_aggregator = StateAggregator(
        jira_client=jira_client,
        checkpointer=checkpointer,
        rate_model=rate_model,
    )

    # 1 & 2. Find checkpoints and filter by project
    project_prefix = f"{project_key.upper()}-"
    all_cps = await list_checkpoints()
    project_ticket_keys = [
        cp["thread_id"] for cp in all_cps if cp["thread_id"].upper().startswith(project_prefix)
    ]

    active_keys = []

    # 3. Filter for active tickets in window
    for key in project_ticket_keys:
        is_active = False

        # Check Jira issue updated timestamp
        try:
            issue = await jira_client.get_issue(key)
            issue_updated = to_utc(issue.updated)
            if issue_updated and start_time <= issue_updated <= end_time:
                is_active = True
        except Exception:
            pass

        # Check checkpoint timestamps for activity in window
        if not is_active:
            try:
                config = {"configurable": {"thread_id": key}}
                async for checkpoint_tuple in checkpointer.alist(config):
                    cp_ts = to_utc(checkpoint_tuple.checkpoint["ts"])
                    if cp_ts and start_time <= cp_ts <= end_time:
                        is_active = True
                        break
            except Exception:
                pass

        if is_active:
            active_keys.append(key)

    # 4 & 5. Aggregate metrics across active tickets
    total_duration = 0.0
    total_phase_durations: dict[str, float] = {}
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0
    ticket_metrics_map = {}

    for key in active_keys:
        # Get history
        history = await state_aggregator.get_ticket_history(key, end_time=end_time)

        # Retrieve token usage and model from latest checkpoint
        token_usage_dict = {"input": 0, "output": 0}
        model_name = None
        try:
            config = {"configurable": {"thread_id": key}}
            latest_cp = await checkpointer.aget(config)
            if latest_cp:
                channel_values = latest_cp.get("channel_values", {})
                cp_tokens = channel_values.get("token_usage")
                if cp_tokens:
                    token_usage_dict = {
                        "input": cp_tokens.get("input", 0),
                        "output": cp_tokens.get("output", 0),
                    }
                model_name = channel_values.get("llm_model") or channel_values.get("model")
        except Exception:
            pass

        cost = state_aggregator.calculate_cost(
            history, token_usage=token_usage_dict, model_name=model_name
        )

        ticket_duration = sum(history.phase_durations.values())
        total_duration += ticket_duration

        for phase, dur in history.phase_durations.items():
            total_phase_durations[phase] = total_phase_durations.get(phase, 0.0) + dur

        total_input_tokens += token_usage_dict["input"]
        total_output_tokens += token_usage_dict["output"]
        total_cost += cost

        ticket_metrics_map[key] = TicketMetrics(
            ticket_key=key,
            durations=history.phase_durations,
            token_usage=TokenUsage(
                input=token_usage_dict["input"],
                output=token_usage_dict["output"],
                total=token_usage_dict["input"] + token_usage_dict["output"],
            ),
            cost=cost,
        )

    if close_jira:
        await jira_client.close()

    report = WeeklyReportMetrics(
        project_key=project_key.upper(),
        window_days=days,
        start_time=start_time.isoformat(),
        end_time=end_time.isoformat(),
        active_tickets=sorted(active_keys),
        total_duration_seconds=total_duration,
        phase_durations=total_phase_durations,
        token_usage=TokenUsage(
            input=total_input_tokens,
            output=total_output_tokens,
            total=total_input_tokens + total_output_tokens,
        ),
        total_cost=total_cost,
        tickets=ticket_metrics_map,
    )

    return report
