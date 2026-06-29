"""Unit tests for StateAggregator and ticket traversal."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from forge.integrations.jira.client import JiraClient
from forge.integrations.jira.models import JiraIssue
from forge.workflow.stats.aggregator import RateModel, StateAggregator, StateHistory, to_utc


class MockCheckpointTuple:
    """Mock for LangGraph CheckpointTuple."""

    def __init__(
        self,
        ts: str,
        current_node: str,
        labels: list[str] | None = None,
        token_usage: dict[str, int] | None = None,
        llm_model: str | None = None,
    ):
        self.checkpoint = {
            "ts": ts,
            "channel_values": {
                "current_node": current_node,
                "labels": labels or [],
                "token_usage": token_usage,
                "llm_model": llm_model,
            },
        }


@pytest.fixture
def mock_jira_client():
    """Create a mocked JiraClient."""
    client = MagicMock(spec=JiraClient)
    client.get_issue = AsyncMock()
    client.get_epic_children = AsyncMock()
    return client


@pytest.fixture
def mock_checkpointer():
    """Create a mocked checkpointer."""
    checkpointer = AsyncMock()
    checkpointer.alist = MagicMock()
    checkpointer.aget = AsyncMock()
    return checkpointer


@pytest.fixture
def default_rate_model():
    """Create a default RateModel."""
    return RateModel(
        phase_hourly_rates={"prd_generation": 10.0, "implementation": 20.0},
        default_hourly_rate=5.0,
        input_token_rate_per_million=3.0,
        output_token_rate_per_million=15.0,
    )


@pytest.mark.asyncio
async def test_to_utc():
    """Test the to_utc timezone utility."""
    # From string
    dt_str = "2024-03-30T10:00:00Z"
    dt = to_utc(dt_str)
    assert dt.tzinfo == UTC
    assert dt.hour == 10

    # From naive datetime
    dt_naive = datetime(2024, 3, 30, 10, 0, 0)
    dt_conv = to_utc(dt_naive)
    assert dt_conv.tzinfo == UTC

    # From aware datetime
    dt_aware = datetime(2024, 3, 30, 10, 0, 0, tzinfo=UTC)
    dt_conv_2 = to_utc(dt_aware)
    assert dt_conv_2 == dt_aware


@pytest.mark.asyncio
async def test_traverse_ticket_hierarchy(mock_jira_client):
    """Test ticket hierarchy traversal up and down."""
    # Hierarchy structure:
    # FEATURE-1 (Root)
    #   -> EPIC-1
    #       -> TASK-1
    #       -> TASK-2
    #   -> EPIC-2

    # Issue mocks
    issue_task_1 = MagicMock(spec=JiraIssue)
    issue_task_1.key = "TASK-1"
    issue_task_1.parent_key = "EPIC-1"

    issue_epic_1 = MagicMock(spec=JiraIssue)
    issue_epic_1.key = "EPIC-1"
    issue_epic_1.parent_key = "FEATURE-1"

    issue_feature_1 = MagicMock(spec=JiraIssue)
    issue_feature_1.key = "FEATURE-1"
    issue_feature_1.parent_key = None

    issue_epic_2 = MagicMock(spec=JiraIssue)
    issue_epic_2.key = "EPIC-2"
    issue_epic_2.parent_key = "FEATURE-1"

    issue_task_2 = MagicMock(spec=JiraIssue)
    issue_task_2.key = "TASK-2"
    issue_task_2.parent_key = "EPIC-1"

    # Mock get_issue
    issues_dict = {
        "TASK-1": issue_task_1,
        "EPIC-1": issue_epic_1,
        "FEATURE-1": issue_feature_1,
        "EPIC-2": issue_epic_2,
        "TASK-2": issue_task_2,
    }

    async def get_issue_mock(key):
        if key in issues_dict:
            return issues_dict[key]
        raise ValueError(f"Unknown key: {key}")

    mock_jira_client.get_issue.side_effect = get_issue_mock

    # Mock get_epic_children
    async def get_epic_children_mock(key):
        if key == "FEATURE-1":
            return [issue_epic_1, issue_epic_2]
        elif key == "EPIC-1":
            return [issue_task_1, issue_task_2]
        return []

    mock_jira_client.get_epic_children.side_effect = get_epic_children_mock

    aggregator = StateAggregator(mock_jira_client)

    # Traverse starting from TASK-1
    related = await aggregator.traverse_ticket_hierarchy("TASK-1")
    expected = {"TASK-1", "EPIC-1", "FEATURE-1", "EPIC-2", "TASK-2"}
    assert set(related) == expected


@pytest.mark.asyncio
async def test_get_related_tickets_in_window(mock_jira_client, mock_checkpointer):
    """Test filtering related tickets in a rolling window of activity."""
    # Root Feature: Updated 10 days ago (outside window) but has a checkpoint 2 days ago (inside window)
    issue_feature = MagicMock(spec=JiraIssue)
    issue_feature.key = "FEATURE-1"
    issue_feature.parent_key = None
    issue_feature.updated = datetime.now(UTC) - timedelta(days=10)

    # Epic: Updated 2 days ago (inside window)
    issue_epic = MagicMock(spec=JiraIssue)
    issue_epic.key = "EPIC-1"
    issue_epic.parent_key = "FEATURE-1"
    issue_epic.updated = datetime.now(UTC) - timedelta(days=2)

    # Task: Updated 15 days ago, no checkpoints (outside window)
    issue_task = MagicMock(spec=JiraIssue)
    issue_task.key = "TASK-1"
    issue_task.parent_key = "EPIC-1"
    issue_task.updated = datetime.now(UTC) - timedelta(days=15)

    issues_dict = {
        "FEATURE-1": issue_feature,
        "EPIC-1": issue_epic,
        "TASK-1": issue_task,
    }

    async def get_issue_mock(key):
        if key in issues_dict:
            return issues_dict[key]
        raise ValueError(f"Unknown key: {key}")

    mock_jira_client.get_issue.side_effect = get_issue_mock
    mock_jira_client.get_epic_children.side_effect = lambda key: (
        [issue_epic] if key == "FEATURE-1" else ([issue_task] if key == "EPIC-1" else [])
    )

    # Mock checkpoints
    # FEATURE-1 has checkpoints in the window
    async def feature_checkpoint_generator(*_args, **_kwargs):
        yield MockCheckpointTuple(
            (datetime.now(UTC) - timedelta(days=2)).isoformat(), "generate_prd"
        )

    # EPIC-1 has no checkpoints in the window (but is active via Jira updated timestamp)
    async def epic_checkpoint_generator(*_args, **_kwargs):
        # Empty async generator
        return
        yield

    # TASK-1 has no checkpoints at all
    async def task_checkpoint_generator(*_args, **_kwargs):
        return
        yield

    def alist_mock(config):
        tid = config["configurable"]["thread_id"]
        gen = AsyncMock()
        if tid == "FEATURE-1":
            gen.__aiter__.side_effect = feature_checkpoint_generator
        elif tid == "EPIC-1":
            gen.__aiter__.side_effect = epic_checkpoint_generator
        else:
            gen.__aiter__.side_effect = task_checkpoint_generator
        return gen

    mock_checkpointer.alist.side_effect = alist_mock

    aggregator = StateAggregator(mock_jira_client, checkpointer=mock_checkpointer)

    # Window of 7 days
    active = await aggregator.get_related_tickets_in_window("TASK-1", days=7)

    # FEATURE-1 is active (checkpoint 2 days ago)
    # EPIC-1 is active (Jira updated 2 days ago)
    # TASK-1 is not active (updated 15 days ago, no checkpoints)
    assert set(active) == {"FEATURE-1", "EPIC-1"}


@pytest.mark.asyncio
async def test_get_ticket_history_durations(mock_jira_client, mock_checkpointer):
    """Test state duration calculation from checkpoint histories."""
    # 3 Checkpoints:
    # 1. 2024-03-30T10:00:00Z -> node: start, phase: prd_generation
    # 2. 2024-03-30T10:05:00Z -> node: prd_approval_gate, phase: prd_approval
    # 3. 2024-03-30T10:15:00Z -> node: generate_spec, phase: spec_generation

    cp1 = MockCheckpointTuple("2024-03-30T10:00:00Z", "start")
    cp2 = MockCheckpointTuple(
        "2024-03-30T10:05:00Z", "prd_approval_gate", labels=["forge:prd-pending"]
    )
    cp3 = MockCheckpointTuple(
        "2024-03-30T10:15:00Z", "generate_spec", labels=["forge:prd-approved"]
    )

    async def checkpoint_generator(*_args, **_kwargs):
        yield cp1
        yield cp2
        yield cp3

    mock_gen = AsyncMock()
    mock_gen.__aiter__.side_effect = checkpoint_generator
    mock_checkpointer.alist.return_return = mock_gen
    mock_checkpointer.alist.side_effect = lambda _config: mock_gen

    aggregator = StateAggregator(mock_jira_client, checkpointer=mock_checkpointer)

    # Reference end time of 10:25:00
    ref_end_time = datetime(2024, 3, 30, 10, 25, 0, tzinfo=UTC)

    history = await aggregator.get_ticket_history("FEATURE-1", end_time=ref_end_time)

    # Expected node durations:
    # start: 10:00 to 10:05 = 300 seconds
    # prd_approval_gate: 10:05 to 10:15 = 600 seconds
    # generate_spec: 10:15 to 10:25 = 600 seconds
    assert history.node_durations["start"] == 300.0
    assert history.node_durations["prd_approval_gate"] == 600.0
    assert history.node_durations["generate_spec"] == 600.0

    # Expected phase durations:
    # start maps to phase prd_generation
    # prd_approval_gate maps to phase prd_approval
    # generate_spec maps to phase spec_generation
    assert history.phase_durations["prd_generation"] == 300.0
    assert history.phase_durations["prd_approval"] == 600.0
    assert history.phase_durations["spec_generation"] == 600.0


def test_calculate_cost(default_rate_model):
    """Test cost calculations based on rate model and token usage."""
    # Mock StateHistory
    history = StateHistory(
        ticket_key="FEATURE-1",
        transitions=[],
        node_durations={},
        phase_durations={
            "prd_generation": 1800.0,  # 0.5 hours @ $10/hr = $5.00
            "implementation": 3600.0,  # 1.0 hours @ $20/hr = $20.00
            "unknown": 7200.0,  # 2.0 hours @ default $5/hr = $10.00
        },
    )

    aggregator = StateAggregator(None, rate_model=default_rate_model)

    # Token Usage:
    # Input: 500,000 tokens @ $3.00/1M = $1.50
    # Output: 100,000 tokens @ $15.00/1M = $1.50
    token_usage = {"input": 500_000, "output": 100_000}

    cost = aggregator.calculate_cost(history, token_usage=token_usage)

    # Expected Cost:
    # Duration: 5.00 + 20.00 + 10.00 = $35.00
    # Tokens: 1.50 + 1.50 = $3.00
    # Total: $38.00
    assert cost == 38.0


def test_calculate_cost_model_rates(default_rate_model):
    """Test cost calculations with model-specific pricing overrides."""
    history = StateHistory(
        ticket_key="FEATURE-1",
        transitions=[],
        node_durations={},
        phase_durations={},
    )

    aggregator = StateAggregator(None, rate_model=default_rate_model)

    # Claude 3 Opus Rates in default_rate_model: input $15.0/M, output $75.0/M
    # Token Usage:
    # Input: 100,000 tokens @ $15.0/M = $1.50
    # Output: 50,000 tokens @ $75.0/M = $3.75
    # Total: $5.25
    token_usage = {"input": 100_000, "output": 50_000}

    cost = aggregator.calculate_cost(history, token_usage=token_usage, model_name="claude-3-opus")
    assert cost == 5.25


@pytest.mark.asyncio
async def test_aggregate_metrics_in_window(mock_jira_client, mock_checkpointer, default_rate_model):
    """Test full aggregation of metrics across multiple tickets in a rolling window."""
    # Active tickets: FEATURE-1, EPIC-1

    issue_feature = MagicMock(spec=JiraIssue)
    issue_feature.key = "FEATURE-1"
    issue_feature.parent_key = None
    issue_feature.updated = datetime(2024, 3, 30, 11, 0, 0, tzinfo=UTC)

    issue_epic = MagicMock(spec=JiraIssue)
    issue_epic.key = "EPIC-1"
    issue_epic.parent_key = "FEATURE-1"
    issue_epic.updated = datetime(2024, 3, 30, 11, 0, 0, tzinfo=UTC)

    mock_jira_client.get_issue.side_effect = lambda key: (
        issue_feature if key == "FEATURE-1" else issue_epic
    )
    mock_jira_client.get_epic_children.side_effect = lambda key: (
        [issue_epic] if key == "FEATURE-1" else []
    )

    # Checkpoints
    # FEATURE-1:
    # CP1: 10:00:00 -> node: start, phase: prd_generation
    # CP2: 10:30:00 -> node: prd_approval_gate, phase: prd_approval
    # End time: 11:00:00
    # Durations: prd_generation = 1800s (0.5h), prd_approval = 1800s (0.5h)
    # Tokens: Input: 1M, Output: 200k. Cost: 0.5h * 10.0 + 0.5h * 5.0 + 1 * 3.0 + 0.2 * 15.0 = 5.0 + 2.5 + 3.0 + 3.0 = $13.5
    cp_f1 = MockCheckpointTuple("2024-03-30T10:00:00Z", "start")
    cp_f2 = MockCheckpointTuple(
        "2024-03-30T10:30:00Z", "prd_approval_gate", labels=["forge:prd-pending"]
    )

    # EPIC-1:
    # CP1: 10:15:00 -> node: generate_spec, phase: spec_generation
    # CP2: 10:45:00 -> node: spec_approval_gate, phase: spec_approval
    # End time: 11:00:00
    # Durations: spec_generation = 1800s (0.5h), spec_approval = 900s (0.25h)
    # Tokens: Input: 2M, Output: 100k. Cost: 0.5h * 5.0 + 0.25h * 5.0 + 2 * 3.0 + 0.1 * 15.0 = 2.5 + 1.25 + 6.0 + 1.5 = $11.25
    cp_e1 = MockCheckpointTuple("2024-03-30T10:15:00Z", "generate_spec")
    cp_e2 = MockCheckpointTuple(
        "2024-03-30T10:45:00Z", "spec_approval_gate", labels=["forge:spec-pending"]
    )

    # Mock checkpointer `alist` and `aget`
    async def feature_checkpoint_generator(*_args, **_kwargs):
        yield cp_f1
        yield cp_f2

    async def epic_checkpoint_generator(*_args, **_kwargs):
        yield cp_e1
        yield cp_e2

    def alist_mock(config):
        tid = config["configurable"]["thread_id"]
        gen = AsyncMock()
        if tid == "FEATURE-1":
            gen.__aiter__.side_effect = feature_checkpoint_generator
        else:
            gen.__aiter__.side_effect = epic_checkpoint_generator
        return gen

    async def aget_mock(config):
        tid = config["configurable"]["thread_id"]
        # Return the latest checkpoint as a dict with token_usage
        if tid == "FEATURE-1":
            return {
                "channel_values": {
                    "token_usage": {"input": 1_000_000, "output": 200_000},
                }
            }
        else:
            return {
                "channel_values": {
                    "token_usage": {"input": 2_000_000, "output": 100_000},
                }
            }

    mock_checkpointer.alist.side_effect = alist_mock
    mock_checkpointer.aget.side_effect = aget_mock

    aggregator = StateAggregator(
        mock_jira_client, checkpointer=mock_checkpointer, rate_model=default_rate_model
    )

    ref_end_time = datetime(2024, 3, 30, 11, 0, 0, tzinfo=UTC)

    # Perform full aggregation
    metrics = await aggregator.aggregate_metrics_in_window(
        "FEATURE-1", days=7, end_time=ref_end_time
    )

    # Totals verification
    assert set(metrics["active_tickets"]) == {"FEATURE-1", "EPIC-1"}
    # FEATURE-1 duration: 3600s, EPIC-1 duration: 2700s
    assert metrics["total_duration_seconds"] == 6300.0

    # Total Tokens:
    # Input: 1M + 2M = 3M
    # Output: 200k + 100k = 300k
    assert metrics["token_usage"]["input"] == 3_000_000
    assert metrics["token_usage"]["output"] == 300_000

    # Total Cost: $13.5 + $11.25 = $24.75
    assert metrics["total_cost"] == 24.75
