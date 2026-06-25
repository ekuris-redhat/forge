"""Unit tests for the forge stats CLI command."""

import argparse
import json
from unittest.mock import AsyncMock, patch

import pytest

from forge.cli import cmd_stats


def _make_args(ticket: str = "AISOS-123", json_flag: bool = False) -> argparse.Namespace:
    """Create a minimal argparse.Namespace for cmd_stats."""
    return argparse.Namespace(ticket=ticket, json=json_flag)


def _base_state(ticket_key: str = "AISOS-123", **overrides) -> dict:
    """Return a minimal workflow state dict with stats data."""
    state: dict = {
        "ticket_key": ticket_key,
        "ticket_type": "Feature",
        "current_node": "prd_approval_gate",
        "is_paused": False,
        "is_blocked": False,
        "last_error": None,
        "feedback_comment": None,
        "context": {},
        "stage_timestamps": {
            "prd": {
                "stage_name": "prd",
                "iteration_count": 1,
                "machine_time_seconds": 30.0,
                "human_time_seconds": 120.0,
                "input_tokens": 500,
                "output_tokens": 800,
            }
        },
        "stats_pr_urls": ["https://github.com/org/repo/pull/42"],
        "stats_ci_cycles": 2,
        "workflow_outcome": None,
        "stats_outcome_reason": None,
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


class TestArgParsing:
    """Tests for argument parsing."""

    def test_stats_subparser_ticket_argument(self):
        """forge stats ticket argument is parsed correctly."""
        parser = argparse.ArgumentParser(prog="forge")
        subparsers = parser.add_subparsers(dest="command")
        stats_parser = subparsers.add_parser("stats")
        stats_parser.add_argument("ticket")
        stats_parser.add_argument("--json", action="store_true")

        args = parser.parse_args(["stats", "AISOS-123"])
        assert args.command == "stats"
        assert args.ticket == "AISOS-123"
        assert args.json is False

    def test_stats_json_flag_true(self):
        """--json flag is parsed as True when provided."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        stats_parser = subparsers.add_parser("stats")
        stats_parser.add_argument("ticket")
        stats_parser.add_argument("--json", action="store_true")

        args = parser.parse_args(["stats", "AISOS-123", "--json"])
        assert args.json is True

    def test_stats_json_flag_default_false(self):
        """--json flag defaults to False when not provided."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        stats_parser = subparsers.add_parser("stats")
        stats_parser.add_argument("ticket")
        stats_parser.add_argument("--json", action="store_true")

        args = parser.parse_args(["stats", "PROJ-99"])
        assert args.json is False

    def test_ticket_argument_is_required(self):
        """ticket positional argument is required (no default)."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        stats_parser = subparsers.add_parser("stats")
        stats_parser.add_argument("ticket")
        stats_parser.add_argument("--json", action="store_true")

        with pytest.raises(SystemExit):
            parser.parse_args(["stats"])


# ---------------------------------------------------------------------------
# Missing checkpoint
# ---------------------------------------------------------------------------


class TestMissingCheckpoint:
    """Tests for missing or absent checkpoint state."""

    @pytest.mark.asyncio
    async def test_returns_exit_code_1_when_no_checkpoint(self, capsys):
        """Returns exit code 1 when get_checkpoint_state returns None."""
        args = _make_args("AISOS-123")
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=None),
        ):
            result = await cmd_stats(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "No workflow data found for AISOS-123" in captured.out

    @pytest.mark.asyncio
    async def test_missing_message_includes_ticket_key(self, capsys):
        """Error message mentions the specific ticket key."""
        args = _make_args("MYPROJ-999")
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=None),
        ):
            result = await cmd_stats(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "MYPROJ-999" in captured.out

    @pytest.mark.asyncio
    async def test_returns_exit_code_1_when_stage_timestamps_key_absent(self, capsys):
        """Returns exit code 1 when stage_timestamps key is not in state."""
        state_without_stats = {
            "ticket_key": "AISOS-123",
            "ticket_type": "Feature",
            "current_node": "prd_approval_gate",
        }
        args = _make_args("AISOS-123")
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state_without_stats),
        ):
            result = await cmd_stats(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "No workflow data found for AISOS-123" in captured.out

    @pytest.mark.asyncio
    async def test_connection_error_returns_exit_code_1(self, capsys):
        """Returns exit code 1 when get_checkpoint_state raises an exception."""
        args = _make_args("AISOS-123")
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(side_effect=ConnectionError("Redis unavailable")),
        ):
            result = await cmd_stats(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err

    @pytest.mark.asyncio
    async def test_generic_exception_returns_exit_code_1(self):
        """Returns exit code 1 for any unexpected exception from checkpointer."""
        args = _make_args("AISOS-123")
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(side_effect=RuntimeError("unexpected")),
        ):
            result = await cmd_stats(args)

        assert result == 1

    @pytest.mark.asyncio
    async def test_connection_error_prints_ticket_in_stderr(self, capsys):
        """Error message includes ticket key in stderr."""
        args = _make_args("AISOS-777")
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(side_effect=ConnectionError("Redis unavailable")),
        ):
            await cmd_stats(args)

        captured = capsys.readouterr()
        assert "AISOS-777" in captured.err


# ---------------------------------------------------------------------------
# Plain text output
# ---------------------------------------------------------------------------


class TestPlainTextOutput:
    """Tests for human-readable table output (no --json flag)."""

    @pytest.mark.asyncio
    async def test_returns_exit_code_0_on_success(self):
        """Returns exit code 0 when stats are found and displayed."""
        args = _make_args("AISOS-123")
        state = _base_state()
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            result = await cmd_stats(args)

        assert result == 0

    @pytest.mark.asyncio
    async def test_output_contains_stats_heading(self, capsys):
        """Output contains the 'Workflow Statistics' heading."""
        args = _make_args("AISOS-123")
        state = _base_state()
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            await cmd_stats(args)

        captured = capsys.readouterr()
        assert "Workflow Statistics" in captured.out

    @pytest.mark.asyncio
    async def test_output_contains_outcome(self, capsys):
        """Output contains the Outcome line."""
        args = _make_args("AISOS-123")
        state = _base_state()
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            await cmd_stats(args)

        captured = capsys.readouterr()
        assert "Outcome" in captured.out

    @pytest.mark.asyncio
    async def test_output_contains_stage_label(self, capsys):
        """Output contains PRD stage label."""
        args = _make_args("AISOS-123")
        state = _base_state()
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            await cmd_stats(args)

        captured = capsys.readouterr()
        assert "PRD" in captured.out

    @pytest.mark.asyncio
    async def test_output_is_not_json(self, capsys):
        """Plain text output is not valid JSON."""
        args = _make_args("AISOS-123")
        state = _base_state()
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            await cmd_stats(args)

        captured = capsys.readouterr()
        try:
            json.loads(captured.out)
            is_json = True
        except (json.JSONDecodeError, ValueError):
            is_json = False
        assert not is_json

    @pytest.mark.asyncio
    async def test_empty_stages_still_returns_exit_code_0(self):
        """Empty stage_timestamps dict (present key, empty value) returns exit 0."""
        state = _base_state(stage_timestamps={})
        args = _make_args("AISOS-123")
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            result = await cmd_stats(args)

        assert result == 0


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


class TestJsonOutput:
    """Tests for --json flag output."""

    @pytest.mark.asyncio
    async def test_json_flag_produces_valid_json(self, capsys):
        """--json flag produces valid JSON output."""
        args = _make_args("AISOS-123", json_flag=True)
        state = _base_state()
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            result = await cmd_stats(args)

        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, dict)

    @pytest.mark.asyncio
    async def test_json_contains_ticket_key(self, capsys):
        """JSON output includes the ticket key."""
        args = _make_args("AISOS-456", json_flag=True)
        state = _base_state(ticket_key="AISOS-456")
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            await cmd_stats(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ticket"] == "AISOS-456"

    @pytest.mark.asyncio
    async def test_json_contains_outcome_field(self, capsys):
        """JSON output includes the outcome field."""
        args = _make_args("AISOS-123", json_flag=True)
        state = _base_state()
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            await cmd_stats(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "outcome" in data

    @pytest.mark.asyncio
    async def test_json_contains_stages(self, capsys):
        """JSON output includes the stages dict."""
        args = _make_args("AISOS-123", json_flag=True)
        state = _base_state()
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            await cmd_stats(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "stages" in data
        assert "prd" in data["stages"]

    @pytest.mark.asyncio
    async def test_json_contains_pr_urls(self, capsys):
        """JSON output includes PR URLs list."""
        args = _make_args("AISOS-123", json_flag=True)
        state = _base_state()
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            await cmd_stats(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "pr_urls" in data
        assert data["pr_urls"] == ["https://github.com/org/repo/pull/42"]

    @pytest.mark.asyncio
    async def test_json_contains_ci_cycles(self, capsys):
        """JSON output includes ci_cycles."""
        args = _make_args("AISOS-123", json_flag=True)
        state = _base_state(stats_ci_cycles=5)
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            await cmd_stats(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ci_cycles"] == 5

    @pytest.mark.asyncio
    async def test_json_returns_exit_code_0(self):
        """--json flag returns exit code 0 on success."""
        args = _make_args("AISOS-123", json_flag=True)
        state = _base_state()
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            result = await cmd_stats(args)

        assert result == 0

    @pytest.mark.asyncio
    async def test_json_contains_outcome_detail(self, capsys):
        """JSON output includes outcome_detail."""
        args = _make_args("AISOS-123", json_flag=True)
        state = _base_state(last_error="build failed", workflow_outcome=None)
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            await cmd_stats(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "outcome_detail" in data
        assert data["outcome_detail"] == "build failed"

    @pytest.mark.asyncio
    async def test_json_empty_stages(self, capsys):
        """JSON output with empty stages contains empty stages dict."""
        args = _make_args("AISOS-123", json_flag=True)
        state = _base_state(stage_timestamps={})
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            await cmd_stats(args)

        data = json.loads(capsys.readouterr().out)
        assert data["stages"] == {}


# ---------------------------------------------------------------------------
# Outcome derivation
# ---------------------------------------------------------------------------


class TestOutcomeDerivation:
    """Tests for outcome derivation logic."""

    @pytest.mark.asyncio
    async def test_pre_set_workflow_outcome_used(self, capsys):
        """workflow_outcome field is used when set."""
        args = _make_args("AISOS-123", json_flag=True)
        state = _base_state(workflow_outcome="Completed")
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            await cmd_stats(args)

        data = json.loads(capsys.readouterr().out)
        assert data["outcome"] == "Completed"

    @pytest.mark.asyncio
    async def test_blocked_outcome_from_is_blocked(self, capsys):
        """Outcome is 'Blocked' when is_blocked is True."""
        args = _make_args("AISOS-123", json_flag=True)
        state = _base_state(
            is_blocked=True,
            workflow_outcome=None,
            feedback_comment="waiting on PM",
        )
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            await cmd_stats(args)

        data = json.loads(capsys.readouterr().out)
        assert data["outcome"] == "Blocked"
        assert data["outcome_detail"] == "waiting on PM"

    @pytest.mark.asyncio
    async def test_failed_outcome_from_last_error(self, capsys):
        """Outcome is 'Failed' when last_error is set."""
        args = _make_args("AISOS-123", json_flag=True)
        state = _base_state(
            is_blocked=False,
            workflow_outcome=None,
            last_error="connection timeout",
        )
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            await cmd_stats(args)

        data = json.loads(capsys.readouterr().out)
        assert data["outcome"] == "Failed"
        assert data["outcome_detail"] == "connection timeout"

    @pytest.mark.asyncio
    async def test_in_progress_outcome_when_no_signals(self, capsys):
        """Outcome defaults to 'In Progress' when no outcome signals found."""
        args = _make_args("AISOS-123", json_flag=True)
        state = _base_state(is_blocked=False, workflow_outcome=None, last_error=None)
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            await cmd_stats(args)

        data = json.loads(capsys.readouterr().out)
        assert data["outcome"] == "In Progress"
        assert data["outcome_detail"] is None

    @pytest.mark.asyncio
    async def test_stats_outcome_reason_used_as_detail(self, capsys):
        """stats_outcome_reason is used as outcome_detail when present."""
        args = _make_args("AISOS-123", json_flag=True)
        state = _base_state(
            workflow_outcome="Blocked",
            stats_outcome_reason="manual hold by PM",
        )
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            await cmd_stats(args)

        data = json.loads(capsys.readouterr().out)
        assert data["outcome_detail"] == "manual hold by PM"

    @pytest.mark.asyncio
    async def test_workflow_outcome_precedence_over_is_blocked(self, capsys):
        """Pre-set workflow_outcome takes precedence over is_blocked flag."""
        args = _make_args("AISOS-123", json_flag=True)
        state = _base_state(workflow_outcome="Completed", is_blocked=True)
        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=state),
        ):
            await cmd_stats(args)

        data = json.loads(capsys.readouterr().out)
        assert data["outcome"] == "Completed"


# ---------------------------------------------------------------------------
# Formatter integration
# ---------------------------------------------------------------------------


class TestFormatterIntegration:
    """Tests that format_stats_summary is called correctly."""

    @pytest.mark.asyncio
    async def test_format_stats_summary_called_for_plain_text(self, capsys):
        """format_stats_summary is invoked for plain text output."""
        args = _make_args("AISOS-123")
        state = _base_state()

        with (
            patch(
                "forge.orchestrator.checkpointer.get_checkpoint_state",
                new=AsyncMock(return_value=state),
            ),
            patch(
                "forge.workflow.stats.formatter.format_stats_summary",
                return_value="mocked summary",
            ) as mock_fmt,
        ):
            await cmd_stats(args)

        mock_fmt.assert_called_once()
        assert "mocked summary" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_format_stats_summary_receives_correct_outcome(self):
        """format_stats_summary is called with derived outcome."""
        args = _make_args("AISOS-123")
        state = _base_state(workflow_outcome="Completed")

        with (
            patch(
                "forge.orchestrator.checkpointer.get_checkpoint_state",
                new=AsyncMock(return_value=state),
            ),
            patch(
                "forge.workflow.stats.formatter.format_stats_summary",
                return_value="ok",
            ) as mock_fmt,
        ):
            await cmd_stats(args)

        call_args = mock_fmt.call_args
        assert call_args[0][1] == "Completed"

    @pytest.mark.asyncio
    async def test_format_stats_summary_not_called_for_json(self):
        """format_stats_summary is NOT called when --json flag is set."""
        args = _make_args("AISOS-123", json_flag=True)
        state = _base_state()

        with (
            patch(
                "forge.orchestrator.checkpointer.get_checkpoint_state",
                new=AsyncMock(return_value=state),
            ),
            patch(
                "forge.workflow.stats.formatter.format_stats_summary",
                return_value="should not appear",
            ) as mock_fmt,
        ):
            await cmd_stats(args)

        mock_fmt.assert_not_called()
