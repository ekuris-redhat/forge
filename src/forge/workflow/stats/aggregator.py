"""Core metrics state aggregation and ticket hierarchy traversal logic."""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from forge.integrations.jira.client import JiraClient
from forge.models.workflow import get_workflow_phase
from forge.orchestrator.checkpointer import get_checkpointer

logger = logging.getLogger(__name__)


def to_utc(dt: datetime | str | None) -> datetime | None:
    """Convert datetime or ISO-format string to timezone-aware UTC datetime."""
    if dt is None:
        return None
    if isinstance(dt, str):
        # Handle Z suffix and convert to ISO offset format
        dt_str = dt.replace("Z", "+00:00")
        dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass
class RateModel:
    """Configurable rate model for computing workflow processing costs."""

    # Hourly rates (USD/hour) for different phases or nodes
    phase_hourly_rates: dict[str, float] = field(default_factory=dict)
    # Default hourly rate if no specific phase rate is defined
    default_hourly_rate: float = 0.0

    # Default token-based costs per million tokens
    input_token_rate_per_million: float = 3.0  # USD per 1M input tokens
    output_token_rate_per_million: float = 15.0  # USD per 1M output tokens

    # Per-model rates (input, output) per million tokens
    model_token_rates: dict[str, dict[str, float]] = field(
        default_factory=lambda: {
            "claude-sonnet-4-5@20250929": {"input": 3.0, "output": 15.0},
            "claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
            "claude-3-opus": {"input": 15.0, "output": 75.0},
            "gemini-2.5-pro": {"input": 1.25, "output": 5.0},
        }
    )


@dataclass
class StateHistory:
    """Reconstructed transition history and durations for a ticket."""

    ticket_key: str
    transitions: list[dict[str, Any]]
    node_durations: dict[str, float]
    phase_durations: dict[str, float]


class StateAggregator:
    """Aggregates workflow metrics across Jira ticket hierarchies."""

    def __init__(
        self,
        jira_client: JiraClient,
        checkpointer: Any | None = None,
        rate_model: RateModel | None = None,
    ):
        """Initialize StateAggregator.

        Args:
            jira_client: The Jira API client.
            checkpointer: Optional LangGraph Redis checkpointer (for fetching histories).
            rate_model: Configurable cost rates. Uses default if not provided.
        """
        self.jira_client = jira_client
        self.checkpointer = checkpointer
        self.rate_model = rate_model or RateModel()

    async def traverse_ticket_hierarchy(self, ticket_key: str) -> list[str]:
        """Traverse ticket ancestry upwards to root and downwards to find related tickets.

        Args:
            ticket_key: Starting ticket key.

        Returns:
            List of all unique related ticket keys in the hierarchy.
        """
        visited_up = set()
        current_key = ticket_key
        root_key = ticket_key

        # Walk up to the root ancestor
        while current_key:
            if current_key in visited_up:
                break
            visited_up.add(current_key)
            root_key = current_key
            try:
                issue = await self.jira_client.get_issue(current_key)
                current_key = issue.parent_key
            except Exception as e:
                logger.warning(
                    f"Error fetching parent for {current_key} during upward traversal: {e}"
                )
                break

        # Walk down from root to find all descendants recursively
        all_related = set()
        to_visit = [root_key]
        while to_visit:
            curr = to_visit.pop(0)
            if curr in all_related:
                continue
            all_related.add(curr)

            try:
                children = await self.jira_client.get_epic_children(curr)
                for child in children:
                    if child.key and child.key not in all_related:
                        to_visit.append(child.key)
            except Exception as e:
                logger.warning(f"Error getting children for {curr} during downward traversal: {e}")

        return list(all_related)

    async def get_related_tickets_in_window(
        self,
        ticket_key: str,
        days: int = 7,
        end_time: datetime | None = None,
    ) -> list[str]:
        """Identify related tickets that had activity during a rolling window.

        Args:
            ticket_key: Start ticket key.
            days: Rolling window size in days (default: 7).
            end_time: End of the rolling window. Defaults to current UTC time.

        Returns:
            List of related ticket keys active in the window.
        """
        end_time = datetime.now(UTC) if end_time is None else to_utc(end_time)

        start_time = end_time - timedelta(days=days)

        # Traverse hierarchy to find all related keys
        related_keys = await self.traverse_ticket_hierarchy(ticket_key)
        active_keys = []

        # Ensure we have checkpointer initialized
        checkpointer = self.checkpointer
        if checkpointer is None:
            try:
                checkpointer = await get_checkpointer()
            except Exception as e:
                logger.warning(f"Could not initialize checkpointer: {e}")

        for key in related_keys:
            is_active = False

            # Check 1: Check Jira issue updated timestamp
            try:
                issue = await self.jira_client.get_issue(key)
                issue_updated = to_utc(issue.updated)
                if issue_updated and start_time <= issue_updated <= end_time:
                    is_active = True
            except Exception as e:
                logger.warning(f"Error checking Jira updated time for {key}: {e}")

            # Check 2: Check checkpoint timestamps for activity in window
            if not is_active and checkpointer is not None:
                try:
                    config = {"configurable": {"thread_id": key}}
                    async for checkpoint_tuple in checkpointer.alist(config):
                        cp_ts = to_utc(checkpoint_tuple.checkpoint["ts"])
                        if cp_ts and start_time <= cp_ts <= end_time:
                            is_active = True
                            break
                except Exception as e:
                    logger.warning(f"Error reading checkpoint times for {key}: {e}")

            if is_active:
                active_keys.append(key)

        return active_keys

    async def get_ticket_history(
        self,
        ticket_key: str,
        end_time: datetime | None = None,
    ) -> StateHistory:
        """Fetch and parse checkpoint histories to reconstruct state transitions and calculate durations.

        Args:
            ticket_key: Ticket key to query.
            end_time: Reference end time for calculating the active/in-progress duration of the last state.

        Returns:
            StateHistory containing transition records and cumulative durations.
        """
        end_time = datetime.now(UTC) if end_time is None else to_utc(end_time)

        config = {"configurable": {"thread_id": ticket_key}}
        checkpoints = []

        try:
            checkpointer = self.checkpointer or await get_checkpointer()
            async for checkpoint_tuple in checkpointer.alist(config):
                checkpoints.append(checkpoint_tuple)
        except Exception as e:
            logger.warning(f"Error fetching checkpoints for {ticket_key}: {e}")

        # Sort checkpoints chronologically
        checkpoints.sort(key=lambda x: to_utc(x.checkpoint["ts"]))

        if not checkpoints:
            return StateHistory(
                ticket_key=ticket_key,
                transitions=[],
                node_durations={},
                phase_durations={},
            )

        def get_phase_from_checkpoint(cp_tuple) -> str:
            channel_values = cp_tuple.checkpoint.get("channel_values", {})
            labels = channel_values.get("labels") or []

            # Also check context if labels are nested
            if not labels and "context" in channel_values:
                labels = channel_values["context"].get("labels") or []
            if not labels and isinstance(channel_values.get("context"), dict):
                labels = channel_values["context"].get("labels") or []

            phase = get_workflow_phase(labels) if labels else None
            if not phase:
                # Map current_node to standard workflow phases as fallback
                node = channel_values.get("current_node", "unknown")
                node_to_phase = {
                    "start": "prd_generation",
                    "generate_prd": "prd_generation",
                    "prd_approval_gate": "prd_approval",
                    "generate_spec": "spec_generation",
                    "spec_approval_gate": "spec_approval",
                    "decompose_epics": "epic_decomposition",
                    "plan_approval_gate": "plan_approval",
                    "generate_tasks": "task_generation",
                    "task_approval_gate": "task_approval",
                    "implement_task": "implementation",
                    "evaluate_ci_status": "ci_evaluation",
                    "attempt_ci_fix": "ci_fix",
                    "human_review_gate": "human_review",
                    "complete": "complete",
                    "triage": "triage_gate",
                }
                phase = node_to_phase.get(node, "unknown")
            return phase

        transitions = []
        node_durations = {}
        phase_durations = {}

        for i in range(len(checkpoints)):
            cp = checkpoints[i]
            ts = to_utc(cp.checkpoint["ts"])
            node = cp.checkpoint.get("channel_values", {}).get("current_node", "unknown")
            phase = get_phase_from_checkpoint(cp)

            # Calculate duration spent in this snapshot
            if i < len(checkpoints) - 1:
                next_ts = to_utc(checkpoints[i + 1].checkpoint["ts"])
                duration = (next_ts - ts).total_seconds()
            else:
                # For the last checkpoint, extend to end_time if it's not a terminal state
                is_terminal = node in ("complete", "closed")
                if not is_terminal and end_time and end_time > ts:
                    duration = (end_time - ts).total_seconds()
                else:
                    duration = 0.0

            transitions.append(
                {
                    "node": node,
                    "phase": phase,
                    "started_at": ts.isoformat(),
                    "duration_seconds": duration,
                }
            )

            if duration > 0:
                node_durations[node] = node_durations.get(node, 0.0) + duration
                phase_durations[phase] = phase_durations.get(phase, 0.0) + duration

        return StateHistory(
            ticket_key=ticket_key,
            transitions=transitions,
            node_durations=node_durations,
            phase_durations=phase_durations,
        )

    def calculate_cost(
        self,
        state_history: StateHistory,
        token_usage: dict[str, int] | None = None,
        model_name: str | None = None,
    ) -> float:
        """Compute workflow processing cost based on duration and tokens.

        Args:
            state_history: Parsed StateHistory for the ticket.
            token_usage: Token counts dict containing "input" and "output".
            model_name: Name of model for token rate lookup.

        Returns:
            Calculated cost in USD.
        """
        # 1. Compute duration cost
        duration_cost = 0.0
        for phase, duration_sec in state_history.phase_durations.items():
            duration_hours = duration_sec / 3600.0
            rate = self.rate_model.phase_hourly_rates.get(
                phase, self.rate_model.default_hourly_rate
            )
            duration_cost += duration_hours * rate

        # 2. Compute token cost
        token_cost = 0.0
        if token_usage:
            input_tokens = token_usage.get("input", 0)
            output_tokens = token_usage.get("output", 0)

            # Determine rate per million
            input_rate = self.rate_model.input_token_rate_per_million
            output_rate = self.rate_model.output_token_rate_per_million

            if model_name and model_name in self.rate_model.model_token_rates:
                input_rate = self.rate_model.model_token_rates[model_name]["input"]
                output_rate = self.rate_model.model_token_rates[model_name]["output"]

            token_cost += (input_tokens / 1_000_000.0) * input_rate
            token_cost += (output_tokens / 1_000_000.0) * output_rate

        return duration_cost + token_cost

    async def aggregate_metrics_in_window(
        self,
        ticket_key: str,
        days: int = 7,
        end_time: datetime | None = None,
    ) -> dict[str, Any]:
        """Aggregate total durations, token usage, and cost for related tickets within the rolling window.

        Args:
            ticket_key: Key of starting ticket.
            days: Size of rolling window in days.
            end_time: Reference end of window.

        Returns:
            Dict containing aggregated metrics and per-ticket details.
        """
        end_time = datetime.now(UTC) if end_time is None else to_utc(end_time)

        # 1. Traverse and find active related keys in the window
        active_keys = await self.get_related_tickets_in_window(
            ticket_key, days=days, end_time=end_time
        )

        total_duration = 0.0
        total_phase_durations = {}
        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = 0.0
        ticket_details = {}

        # 2. Accumulate history, tokens, and cost for each active ticket
        for key in active_keys:
            history = await self.get_ticket_history(key, end_time=end_time)

            # Find token usage from latest checkpoint if available
            token_usage = None
            model_name = None
            try:
                config = {"configurable": {"thread_id": key}}
                checkpointer = self.checkpointer or await get_checkpointer()
                latest_cp = await checkpointer.aget(config)
                if latest_cp:
                    channel_values = latest_cp.get("channel_values", {})
                    token_usage = channel_values.get("token_usage")
                    model_name = channel_values.get("llm_model") or channel_values.get("model")
            except Exception as e:
                logger.warning(f"Could not retrieve latest checkpoint token values for {key}: {e}")

            # Calculate individual cost
            cost = self.calculate_cost(history, token_usage=token_usage, model_name=model_name)

            # Accumulate totals
            ticket_duration = sum(history.phase_durations.values())
            total_duration += ticket_duration

            for phase, dur in history.phase_durations.items():
                total_phase_durations[phase] = total_phase_durations.get(phase, 0.0) + dur

            if token_usage:
                total_input_tokens += token_usage.get("input", 0)
                total_output_tokens += token_usage.get("output", 0)

            total_cost += cost

            ticket_details[key] = {
                "durations": history.phase_durations,
                "token_usage": token_usage or {"input": 0, "output": 0},
                "cost": cost,
            }

        return {
            "window_days": days,
            "end_time": end_time.isoformat(),
            "active_tickets": active_keys,
            "total_duration_seconds": total_duration,
            "phase_durations": total_phase_durations,
            "token_usage": {
                "input": total_input_tokens,
                "output": total_output_tokens,
            },
            "total_cost": total_cost,
            "tickets": ticket_details,
        }
