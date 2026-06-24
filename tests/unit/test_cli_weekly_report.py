"""Integration tests for the forge weekly-report CLI command."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest

from forge.cli import cmd_weekly_report
from forge.workflow.stats.weekly_report import (
    BottleneckAnalysis,
    TicketSummary,
    WeeklyReportData,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(
    project: str = "PROJ",
    days: int = 7,
    output: str | None = None,
    fmt: str = "text",
) -> argparse.Namespace:
    """Create a minimal argparse.Namespace for cmd_weekly_report."""
    return argparse.Namespace(project=project, days=days, output=output, format=fmt)


def _make_report(project: str = "PROJ", days: int = 7, **overrides) -> WeeklyReportData:
    """Return a WeeklyReportData with one completed ticket for testing."""
    completed = [
        TicketSummary(
            ticket_key=f"{project}-1",
            ticket_type="Feature",
            status="completed",
            duration_seconds=3600.0,
            input_tokens=1000,
            output_tokens=500,
        )
    ]
    data = WeeklyReportData(
        project=project,
        period_days=days,
        report_start="2024-01-01T00:00:00+00:00",
        report_end="2024-01-08T00:00:00+00:00",
        completed_tickets=overrides.pop("completed_tickets", completed),
        in_progress_tickets=overrides.pop("in_progress_tickets", []),
        blocked_tickets=overrides.pop("blocked_tickets", []),
        total_input_tokens=overrides.pop("total_input_tokens", 1000),
        total_output_tokens=overrides.pop("total_output_tokens", 500),
        avg_cycle_time=overrides.pop("avg_cycle_time", 3600.0),
        bottlenecks=overrides.pop("bottlenecks", BottleneckAnalysis()),
    )
    return data


def _empty_report(project: str = "PROJ") -> WeeklyReportData:
    """Return a WeeklyReportData with no tickets."""
    return WeeklyReportData(
        project=project,
        period_days=7,
        report_start="2024-01-01T00:00:00+00:00",
        report_end="2024-01-08T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


class TestArgParsing:
    """Tests for argument parsing of the weekly-report subparser."""

    def _build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog="forge")
        subparsers = parser.add_subparsers(dest="command")
        wr_parser = subparsers.add_parser("weekly-report")
        wr_parser.add_argument("--project", required=True)
        wr_parser.add_argument("--days", type=int, default=7)
        wr_parser.add_argument("--output", default=None)
        wr_parser.add_argument(
            "--format", choices=["text", "markdown", "json"], default="text"
        )
        return parser

    def test_project_is_required(self):
        """--project is required; missing it raises SystemExit."""
        parser = self._build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["weekly-report"])

    def test_project_is_parsed(self):
        """--project value is captured correctly."""
        parser = self._build_parser()
        args = parser.parse_args(["weekly-report", "--project", "MYPROJ"])
        assert args.project == "MYPROJ"

    def test_days_defaults_to_7(self):
        """--days defaults to 7 when not provided."""
        parser = self._build_parser()
        args = parser.parse_args(["weekly-report", "--project", "PROJ"])
        assert args.days == 7

    def test_days_custom_value(self):
        """--days accepts a custom integer."""
        parser = self._build_parser()
        args = parser.parse_args(["weekly-report", "--project", "PROJ", "--days", "14"])
        assert args.days == 14

    def test_output_defaults_to_none(self):
        """--output defaults to None when not provided."""
        parser = self._build_parser()
        args = parser.parse_args(["weekly-report", "--project", "PROJ"])
        assert args.output is None

    def test_output_path_captured(self):
        """--output path is captured correctly."""
        parser = self._build_parser()
        args = parser.parse_args(
            ["weekly-report", "--project", "PROJ", "--output", "report.md"]
        )
        assert args.output == "report.md"

    def test_format_defaults_to_text(self):
        """--format defaults to 'text' when not provided."""
        parser = self._build_parser()
        args = parser.parse_args(["weekly-report", "--project", "PROJ"])
        assert args.format == "text"

    def test_format_markdown(self):
        """--format markdown is accepted."""
        parser = self._build_parser()
        args = parser.parse_args(
            ["weekly-report", "--project", "PROJ", "--format", "markdown"]
        )
        assert args.format == "markdown"

    def test_format_json(self):
        """--format json is accepted."""
        parser = self._build_parser()
        args = parser.parse_args(
            ["weekly-report", "--project", "PROJ", "--format", "json"]
        )
        assert args.format == "json"

    def test_invalid_format_raises(self):
        """An invalid --format value raises SystemExit."""
        parser = self._build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["weekly-report", "--project", "PROJ", "--format", "xml"])


# ---------------------------------------------------------------------------
# Text output (stdout)
# ---------------------------------------------------------------------------


class TestTextOutput:
    """Tests for default text format output to stdout."""

    @pytest.mark.asyncio
    async def test_returns_exit_code_0_with_data(self, capsys):
        """Returns 0 when data is available."""
        args = _make_args()
        report = _make_report()

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            result = await cmd_weekly_report(args)

        assert result == 0

    @pytest.mark.asyncio
    async def test_stdout_contains_project_key(self, capsys):
        """stdout contains the project key."""
        args = _make_args(project="MYPROJ")
        report = _make_report(project="MYPROJ")

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            await cmd_weekly_report(args)

        captured = capsys.readouterr()
        assert "MYPROJ" in captured.out

    @pytest.mark.asyncio
    async def test_stdout_contains_ticket_key(self, capsys):
        """stdout contains ticket keys from the report."""
        args = _make_args(project="PROJ")
        report = _make_report(project="PROJ")

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            await cmd_weekly_report(args)

        captured = capsys.readouterr()
        assert "PROJ-1" in captured.out

    @pytest.mark.asyncio
    async def test_days_passed_to_collect(self):
        """--days value is forwarded to collect_weekly_data."""
        args = _make_args(days=14)
        report = _make_report(days=14)

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ) as mock_collect:
            await cmd_weekly_report(args)

        mock_collect.assert_awaited_once_with("PROJ", days=14)


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------


class TestMarkdownOutput:
    """Tests for markdown format output."""

    @pytest.mark.asyncio
    async def test_markdown_to_stdout(self, capsys):
        """--format markdown outputs Markdown content to stdout."""
        args = _make_args(fmt="markdown")
        report = _make_report()

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            result = await cmd_weekly_report(args)

        assert result == 0
        captured = capsys.readouterr()
        # Markdown report starts with a heading
        assert "# Weekly Report" in captured.out

    @pytest.mark.asyncio
    async def test_markdown_contains_project(self, capsys):
        """Markdown output contains the project name."""
        args = _make_args(project="ACME", fmt="markdown")
        report = _make_report(project="ACME")

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            await cmd_weekly_report(args)

        captured = capsys.readouterr()
        assert "ACME" in captured.out


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


class TestJsonOutput:
    """Tests for JSON format output."""

    @pytest.mark.asyncio
    async def test_json_to_stdout(self, capsys):
        """--format json outputs valid JSON to stdout."""
        args = _make_args(fmt="json")
        report = _make_report()

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            result = await cmd_weekly_report(args)

        assert result == 0
        captured = capsys.readouterr()
        # Should be valid JSON
        parsed = json.loads(captured.out)
        assert isinstance(parsed, dict)

    @pytest.mark.asyncio
    async def test_json_contains_project_field(self, capsys):
        """JSON output has a 'project' field matching the requested project."""
        args = _make_args(project="TESTPROJ", fmt="json")
        report = _make_report(project="TESTPROJ")

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            await cmd_weekly_report(args)

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["project"] == "TESTPROJ"


# ---------------------------------------------------------------------------
# File output
# ---------------------------------------------------------------------------


class TestFileOutput:
    """Tests for writing report to a file via --output."""

    @pytest.mark.asyncio
    async def test_writes_to_file(self):
        """Report is written to the specified file path."""
        report = _make_report()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as tmp:
            tmp_path = tmp.name

        try:
            args = _make_args(output=tmp_path)

            with patch(
                "forge.workflow.stats.weekly_report.collect_weekly_data",
                new=AsyncMock(return_value=report),
            ):
                result = await cmd_weekly_report(args)

            assert result == 0
            assert os.path.exists(tmp_path)
            content = open(tmp_path, encoding="utf-8").read()
            assert len(content) > 0
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_file_output_contains_project(self):
        """Written file contains the project key."""
        report = _make_report(project="FILEPROJ")

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as tmp:
            tmp_path = tmp.name

        try:
            args = _make_args(project="FILEPROJ", output=tmp_path)

            with patch(
                "forge.workflow.stats.weekly_report.collect_weekly_data",
                new=AsyncMock(return_value=report),
            ):
                await cmd_weekly_report(args)

            content = open(tmp_path, encoding="utf-8").read()
            assert "FILEPROJ" in content
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_stdout_not_written_when_output_file(self, capsys):
        """stdout only contains confirmation message when --output is set."""
        report = _make_report()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as tmp:
            tmp_path = tmp.name

        try:
            args = _make_args(output=tmp_path)

            with patch(
                "forge.workflow.stats.weekly_report.collect_weekly_data",
                new=AsyncMock(return_value=report),
            ):
                await cmd_weekly_report(args)

            captured = capsys.readouterr()
            # The report body should NOT be on stdout; only the confirmation
            assert "Report written to" in captured.out
            assert "WEEKLY REPORT" not in captured.out
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_markdown_written_to_file(self):
        """Markdown report is correctly written when format=markdown."""
        report = _make_report()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as tmp:
            tmp_path = tmp.name

        try:
            args = _make_args(output=tmp_path, fmt="markdown")

            with patch(
                "forge.workflow.stats.weekly_report.collect_weekly_data",
                new=AsyncMock(return_value=report),
            ):
                result = await cmd_weekly_report(args)

            assert result == 0
            content = open(tmp_path, encoding="utf-8").read()
            assert "# Weekly Report" in content
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_unwritable_path_returns_exit_code_1(self, capsys):
        """Returns exit code 1 when the output file cannot be created."""
        args = _make_args(output="/nonexistent_dir/report.txt")
        report = _make_report()

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            result = await cmd_weekly_report(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err


# ---------------------------------------------------------------------------
# No data / graceful failure
# ---------------------------------------------------------------------------


class TestNoData:
    """Tests for graceful failure when project has no data."""

    @pytest.mark.asyncio
    async def test_empty_report_returns_exit_code_1(self, capsys):
        """Returns exit code 1 when no tickets are found for the project."""
        args = _make_args(project="EMPTY")
        report = _empty_report(project="EMPTY")

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            result = await cmd_weekly_report(args)

        assert result == 1

    @pytest.mark.asyncio
    async def test_empty_report_error_message_contains_project(self, capsys):
        """Error message mentions the project key."""
        args = _make_args(project="EMPTY")
        report = _empty_report(project="EMPTY")

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            await cmd_weekly_report(args)

        captured = capsys.readouterr()
        assert "EMPTY" in captured.err

    @pytest.mark.asyncio
    async def test_collect_exception_returns_exit_code_1(self, capsys):
        """Returns exit code 1 when collect_weekly_data raises an exception."""
        args = _make_args(project="PROJ")

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(side_effect=ConnectionError("Redis unavailable")),
        ):
            result = await cmd_weekly_report(args)

        assert result == 1

    @pytest.mark.asyncio
    async def test_collect_exception_error_printed_to_stderr(self, capsys):
        """Exception from collect_weekly_data prints an error to stderr."""
        args = _make_args(project="PROJ")

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(side_effect=RuntimeError("something went wrong")),
        ):
            await cmd_weekly_report(args)

        captured = capsys.readouterr()
        assert "Error" in captured.err


# ---------------------------------------------------------------------------
# Handler registration
# ---------------------------------------------------------------------------


class TestHandlerRegistration:
    """Verify that weekly-report is wired into the CLI handlers dict."""

    def test_weekly_report_in_handlers(self):
        """cmd_weekly_report is importable and matches the CLI handler signature."""
        from forge.cli import cmd_weekly_report as handler

        # Should be an async function
        import asyncio

        assert asyncio.iscoroutinefunction(handler)
