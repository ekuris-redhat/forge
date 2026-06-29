"""Unit tests for report formatting and idempotent writing logic."""

import os
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.workflow.stats.reporter import (
    TicketMetrics,
    TokenUsage,
    WeeklyReportMetrics,
    format_duration,
    generate_weekly_report,
    publish_report_idempotently,
)


def test_format_duration():
    """Test format_duration helper."""
    assert format_duration(0) == "0s"
    assert format_duration(-10) == "0s"
    assert format_duration(45) == "45s"
    assert format_duration(120) == "2m"
    assert format_duration(125) == "2m 5s"
    assert format_duration(3600) == "1h"
    assert format_duration(3665) == "1h 1m 5s"


def test_weekly_report_metrics_json_schema():
    """Test WeeklyReportMetrics JSON serialization and schema validation."""
    report = WeeklyReportMetrics(
        project_key="PROJ",
        window_days=7,
        start_time="2026-05-01T00:00:00Z",
        end_time="2026-05-08T00:00:00Z",
        active_tickets=["PROJ-101", "PROJ-102"],
        total_duration_seconds=3600.0,
        phase_durations={"prd_generation": 1200.0, "implementation": 2400.0},
        token_usage=TokenUsage(input=5000, output=3000, total=8000),
        total_cost=0.50,
        tickets={
            "PROJ-101": TicketMetrics(
                ticket_key="PROJ-101",
                durations={"prd_generation": 1200.0},
                token_usage=TokenUsage(input=2000, output=1000, total=3000),
                cost=0.15,
            ),
            "PROJ-102": TicketMetrics(
                ticket_key="PROJ-102",
                durations={"implementation": 2400.0},
                token_usage=TokenUsage(input=3000, output=2000, total=5000),
                cost=0.35,
            ),
        },
    )

    # Convert to JSON and parse back to validate schema
    json_str = report.to_json()
    parsed_report = WeeklyReportMetrics.model_validate_json(json_str)

    assert parsed_report.project_key == "PROJ"
    assert parsed_report.window_days == 7
    assert parsed_report.token_usage.total == 8000
    assert len(parsed_report.active_tickets) == 2
    assert "PROJ-101" in parsed_report.tickets
    assert parsed_report.tickets["PROJ-101"].cost == 0.15


def test_weekly_report_metrics_to_markdown():
    """Test markdown report formatting."""
    report = WeeklyReportMetrics(
        project_key="PROJ",
        window_days=7,
        start_time="2026-05-01T00:00:00Z",
        end_time="2026-05-08T00:00:00Z",
        active_tickets=["PROJ-101"],
        total_duration_seconds=3600.0,
        phase_durations={"prd_generation": 3600.0},
        token_usage=TokenUsage(input=5000, output=3000, total=8000),
        total_cost=0.50,
        tickets={
            "PROJ-101": TicketMetrics(
                ticket_key="PROJ-101",
                durations={"prd_generation": 3600.0},
                token_usage=TokenUsage(input=5000, output=3000, total=8000),
                cost=0.50,
            )
        },
    )

    md = report.to_markdown()

    assert "# Weekly Status Report: PROJ" in md
    assert "**Reporting Period:** 2026-05-01T00:00:00Z to 2026-05-08T00:00:00Z (7 days)" in md
    assert "**Total Cost:** $0.5000 USD" in md
    assert "**Total Duration:** 1h" in md
    assert "prd_generation" in md
    assert "Ticket: PROJ-101" in md
    assert "5,000 input / 3,000 output" in md


def test_publish_report_idempotently_creates_new():
    """Test publish_report_idempotently creates a new file if it does not exist."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        file_path = os.path.join(tmp_dir, "weekly_report.md")
        start_time = "2026-05-01T00:00:00Z"
        end_time = "2026-05-08T00:00:00Z"
        report_content = "This is a report content."

        publish_report_idempotently(file_path, report_content, start_time, end_time)

        assert os.path.exists(file_path)
        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        expected = (
            f"<!-- FORGE-WEEKLY-REPORT-START: {start_time} TO {end_time} -->\n"
            f"{report_content}\n"
            f"<!-- FORGE-WEEKLY-REPORT-END -->"
        )
        assert content == expected


def test_publish_report_idempotently_updates_existing():
    """Test publish_report_idempotently updates existing report matching the markers."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        file_path = os.path.join(tmp_dir, "weekly_report.md")
        start_time = "2026-05-01T00:00:00Z"
        end_time = "2026-05-08T00:00:00Z"

        # Initial write
        publish_report_idempotently(file_path, "Old Report Content", start_time, end_time)

        # Update write (same timeframe)
        publish_report_idempotently(file_path, "New Report Content", start_time, end_time)

        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        expected = (
            f"<!-- FORGE-WEEKLY-REPORT-START: {start_time} TO {end_time} -->\n"
            f"New Report Content\n"
            f"<!-- FORGE-WEEKLY-REPORT-END -->"
        )
        assert content == expected


def test_publish_report_idempotently_prepends_new_timeframe():
    """Test publish_report_idempotently prepends a new timeframe report if the file is not empty."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        file_path = os.path.join(tmp_dir, "weekly_report.md")
        t1_start = "2026-05-01T00:00:00Z"
        t1_end = "2026-05-08T00:00:00Z"
        t2_start = "2026-05-08T00:00:00Z"
        t2_end = "2026-05-15T00:00:00Z"

        # Write first timeframe
        publish_report_idempotently(file_path, "Report Week 1", t1_start, t1_end)

        # Write second timeframe
        publish_report_idempotently(file_path, "Report Week 2", t2_start, t2_end)

        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        assert "Report Week 2" in content
        assert "Report Week 1" in content
        # Week 2 should be prepended before Week 1
        assert content.index("Report Week 2") < content.index("Report Week 1")


@pytest.mark.asyncio
@patch("forge.orchestrator.checkpointer.list_checkpoints")
@patch("forge.orchestrator.checkpointer.get_checkpointer")
async def test_generate_weekly_report(mock_get_checkpointer, mock_list_checkpoints):
    """Test generate_weekly_report aggregation logic with mocked dependencies."""
    # Mock list_checkpoints to return thread IDs
    mock_list_checkpoints.return_value = [
        {"thread_id": "PROJ-101"},
        {"thread_id": "PROJ-102"},
        {"thread_id": "OTHER-101"},  # should be filtered out
    ]

    # Mock checkpointer
    mock_checkpointer = AsyncMock()
    mock_checkpointer.alist = MagicMock()
    mock_get_checkpointer.return_value = mock_checkpointer

    # Setup mock checkpoint alist generator for active in window
    class MockCheckpointTuple:
        def __init__(self, ts):
            self.checkpoint = {"ts": ts}

    async def mock_alist_proj_101(*_args, **_kwargs):
        # PROJ-101 has checkpoint in the window
        yield MockCheckpointTuple((datetime.now(UTC) - timedelta(days=2)).isoformat())

    async def mock_alist_proj_102(*_args, **_kwargs):
        # PROJ-102 has checkpoint in the window
        yield MockCheckpointTuple((datetime.now(UTC) - timedelta(days=3)).isoformat())

    def mock_alist(config):
        tid = config["configurable"]["thread_id"]
        gen = AsyncMock()
        if tid == "PROJ-101":
            gen.__aiter__.side_effect = mock_alist_proj_101
        elif tid == "PROJ-102":
            gen.__aiter__.side_effect = mock_alist_proj_102
        return gen

    mock_checkpointer.alist.side_effect = mock_alist

    # Setup mock checkpoint aget for token usage & model
    async def mock_aget(config):
        tid = config["configurable"]["thread_id"]
        if tid == "PROJ-101":
            return {
                "channel_values": {
                    "token_usage": {"input": 1000, "output": 500},
                    "llm_model": "claude-3-5-sonnet",
                }
            }
        elif tid == "PROJ-102":
            return {
                "channel_values": {
                    "token_usage": {"input": 2000, "output": 1000},
                    "model": "claude-3-5-sonnet",
                }
            }
        return None

    mock_checkpointer.aget.side_effect = mock_aget

    # Mock JiraClient
    mock_jira = AsyncMock()
    # Ensure getting issue doesn't throw or override activity (updated is long ago)
    mock_issue = MagicMock()
    mock_issue.updated = (datetime.now(UTC) - timedelta(days=20)).isoformat()
    mock_jira.get_issue.return_value = mock_issue

    # Mock StateHistory retrieval
    from forge.workflow.stats.aggregator import StateHistory

    with patch(
        "forge.workflow.stats.aggregator.StateAggregator.get_ticket_history"
    ) as mock_get_history:
        # PROJ-101 history
        hist1 = StateHistory(
            ticket_key="PROJ-101",
            transitions=[],
            node_durations={"generate_prd": 300.0},
            phase_durations={"prd_generation": 300.0},
        )
        # PROJ-102 history
        hist2 = StateHistory(
            ticket_key="PROJ-102",
            transitions=[],
            node_durations={"implement_task": 600.0},
            phase_durations={"implementation": 600.0},
        )

        async def get_history_side_effect(key, end_time=None):  # noqa: ARG001
            if key == "PROJ-101":
                return hist1
            return hist2

        mock_get_history.side_effect = get_history_side_effect

        # Call generate_weekly_report
        report = await generate_weekly_report(
            project_key="PROJ",
            days=7,
            jira_client=mock_jira,
            checkpointer=mock_checkpointer,
        )

        assert report.project_key == "PROJ"
        assert report.window_days == 7
        assert sorted(report.active_tickets) == ["PROJ-101", "PROJ-102"]
        assert report.total_duration_seconds == 900.0
        assert report.phase_durations == {"prd_generation": 300.0, "implementation": 600.0}
        assert report.token_usage.input == 3000
        assert report.token_usage.output == 1500
        assert report.token_usage.total == 4500
        assert "PROJ-101" in report.tickets
        assert "PROJ-102" in report.tickets


@pytest.mark.asyncio
@patch("forge.workflow.stats.reporter.generate_weekly_report")
@patch("forge.workflow.stats.reporter.publish_report_idempotently")
async def test_cmd_weekly_report(mock_publish, mock_generate):
    """Test cmd_weekly_report CLI integration."""
    import argparse

    from forge.cli import cmd_weekly_report

    mock_report = MagicMock()
    mock_report.start_time = "2026-05-01T00:00:00Z"
    mock_report.end_time = "2026-05-08T00:00:00Z"
    mock_report.to_markdown.return_value = "MD Report"
    mock_report.to_json.return_value = '{"json": true}'
    mock_generate.return_value = mock_report

    # 1. Test markdown output to file
    args = argparse.Namespace(project="PROJ", days=7, format="markdown", output="report.md")
    res = await cmd_weekly_report(args)
    assert res == 0
    mock_generate.assert_called_with(project_key="PROJ", days=7)
    mock_publish.assert_called_with(
        file_path="report.md",
        report_markdown="MD Report",
        start_time="2026-05-01T00:00:00Z",
        end_time="2026-05-08T00:00:00Z",
    )

    # 2. Test JSON output to file
    with patch("builtins.open", create=True) as mock_file_open:
        args = argparse.Namespace(project="PROJ", days=7, format="json", output="report.json")
        res = await cmd_weekly_report(args)
        assert res == 0
        mock_file_open.assert_called_with("report.json", "w", encoding="utf-8")

