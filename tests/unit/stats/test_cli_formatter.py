"""Unit tests for forge.stats.cli_formatter.

All tests exercise the public API (format_stats_table, format_stats_json)
and the internal helpers without any I/O or external dependencies.
"""

from __future__ import annotations

import json

from forge.stats.cli_formatter import (
    _COLOR_GREEN,
    _COLOR_RED,
    _COLOR_RESET,
    _DASH,
    _colorize,
    _determine_display_stages,
    _fmt_seconds,
    _fmt_tokens,
    _stage_row_values,
    _totals_row_values,
    _truncate,
    format_stats_json,
    format_stats_table,
)
from forge.stats.retrieval import WorkflowStats

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_TICKET = "AISOS-999"


def _make_stage(
    *,
    stage_name: str = "prd",
    iteration_count: int = 1,
    machine_time_seconds: float = 60.0,
    human_time_seconds: float = 120.0,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    started_at: str | None = "2024-01-01T00:00:00+00:00",
    ended_at: str | None = "2024-01-01T00:01:00+00:00",
) -> dict:
    return {
        "stage_name": stage_name,
        "iteration_count": iteration_count,
        "machine_time_seconds": machine_time_seconds,
        "human_time_seconds": human_time_seconds,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "started_at": started_at,
        "ended_at": ended_at,
    }


def _make_stats(**kwargs) -> WorkflowStats:
    """Construct a WorkflowStats with sensible defaults."""
    defaults: dict = {
        "ticket_key": _TICKET,
        "stages": {},
        "pr_urls": [],
        "ci_cycles": 0,
        "outcome": None,
        "outcome_reason": None,
        "comment_posted": False,
        "workflow_run_id": "",
    }
    defaults.update(kwargs)
    return WorkflowStats(**defaults)


# ---------------------------------------------------------------------------
# _fmt_seconds
# ---------------------------------------------------------------------------


class TestFmtSeconds:
    def test_seconds_only(self):
        assert _fmt_seconds(45.0) == "45s"

    def test_minutes_and_seconds(self):
        assert _fmt_seconds(90.0) == "1m 30s"

    def test_hours_minutes_seconds(self):
        assert _fmt_seconds(3661.0) == "1h 1m 1s"

    def test_zero(self):
        assert _fmt_seconds(0.0) == "0s"

    def test_exact_hour(self):
        assert _fmt_seconds(3600.0) == "1h 0m 0s"

    def test_truncates_fractional(self):
        # fractional seconds are truncated
        assert _fmt_seconds(1.9) == "1s"


# ---------------------------------------------------------------------------
# _fmt_tokens
# ---------------------------------------------------------------------------


class TestFmtTokens:
    def test_small_number(self):
        assert _fmt_tokens(500) == "500"

    def test_thousands(self):
        assert _fmt_tokens(1_000) == "1,000"

    def test_millions(self):
        assert _fmt_tokens(1_234_567) == "1,234,567"

    def test_zero(self):
        assert _fmt_tokens(0) == "0"


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short_string_unchanged(self):
        assert _truncate("hello", 10) == "hello"

    def test_exact_length_unchanged(self):
        assert _truncate("12345", 5) == "12345"

    def test_long_string_truncated(self):
        result = _truncate("abcdefghij", 7)
        assert result == "abcd..."
        assert len(result) == 7

    def test_max_len_three_gives_ellipsis(self):
        result = _truncate("hello", 3)
        assert result == "..."


# ---------------------------------------------------------------------------
# _colorize
# ---------------------------------------------------------------------------


class TestColorize:
    def test_no_color_returns_text(self):
        assert _colorize("hello", _COLOR_GREEN, use_color=False) == "hello"

    def test_color_wraps_text(self):
        result = _colorize("OK", _COLOR_GREEN, use_color=True)
        assert _COLOR_GREEN in result
        assert "OK" in result
        assert _COLOR_RESET in result

    def test_color_reset_appended(self):
        result = _colorize("ERR", _COLOR_RED, use_color=True)
        assert result.endswith(_COLOR_RESET)


# ---------------------------------------------------------------------------
# _stage_row_values
# ---------------------------------------------------------------------------


class TestStageRowValues:
    def test_none_stage_returns_dashes(self):
        label, itr, mt, ti, to = _stage_row_values("PRD", None)
        assert label == "PRD"
        assert itr == _DASH
        assert mt == _DASH
        assert ti == _DASH
        assert to == _DASH

    def test_executed_stage_returns_values(self):
        stage = _make_stage(
            iteration_count=2,
            machine_time_seconds=90.0,
            human_time_seconds=30.0,
            input_tokens=1000,
            output_tokens=500,
        )
        label, itr, mt, ti, to = _stage_row_values("PRD", stage)
        assert label == "PRD"
        assert itr == "2"
        assert mt == "1m 30s"
        assert ti == "1,000"
        assert to == "500"

    def test_zero_iteration_count(self):
        stage = _make_stage(iteration_count=0)
        label, itr, *_ = _stage_row_values("Spec", stage)
        assert itr == "0"

    def test_missing_stage_fields_default_to_zero(self):
        stage: dict = {}
        label, itr, mt, ti, to = _stage_row_values("CI", stage)
        assert itr == "0"
        assert mt == "0s"
        assert ti == "0"
        assert to == "0"


# ---------------------------------------------------------------------------
# _totals_row_values
# ---------------------------------------------------------------------------


class TestTotalsRowValues:
    def test_empty_stages_gives_zeros(self):
        label, itr, mt, ti, to = _totals_row_values({})
        assert label == "TOTAL"
        assert itr == ""
        assert mt == "0s"
        assert ti == "0"
        assert to == "0"

    def test_sums_across_stages(self):
        stages = {
            "prd": _make_stage(
                machine_time_seconds=60.0,
                human_time_seconds=30.0,
                input_tokens=1000,
                output_tokens=500,
            ),
            "spec": _make_stage(
                machine_time_seconds=120.0,
                human_time_seconds=60.0,
                input_tokens=2000,
                output_tokens=1000,
            ),
        }
        label, _, mt, ti, to = _totals_row_values(stages)
        assert label == "TOTAL"
        assert mt == "3m 0s"
        assert ti == "3,000"
        assert to == "1,500"


# ---------------------------------------------------------------------------
# _determine_display_stages
# ---------------------------------------------------------------------------


class TestDetermineDisplayStages:
    def test_empty_stages_returns_feature_stages(self):
        from forge.workflow.stats import ALL_FEATURE_STAGES

        result = _determine_display_stages({})
        assert result == ALL_FEATURE_STAGES

    def test_feature_stages_returns_feature_list(self):
        from forge.workflow.stats import ALL_FEATURE_STAGES

        stages = {"prd": {}, "spec": {}}
        result = _determine_display_stages(stages)
        assert result == ALL_FEATURE_STAGES

    def test_bug_stages_returns_bug_list(self):
        from forge.workflow.stats import ALL_BUG_STAGES

        stages = {"triage": {}, "rca": {}}
        result = _determine_display_stages(stages)
        assert result == ALL_BUG_STAGES

    def test_planning_triggers_bug_list(self):
        from forge.workflow.stats import ALL_BUG_STAGES

        stages = {"planning": {}, "implementation": {}}
        result = _determine_display_stages(stages)
        assert result == ALL_BUG_STAGES


# ---------------------------------------------------------------------------
# format_stats_table — basic structure
# ---------------------------------------------------------------------------


class TestFormatStatsTableBasicStructure:
    def test_returns_string(self):
        stats = _make_stats()
        result = format_stats_table(stats)
        assert isinstance(result, str)

    def test_contains_ticket_key(self):
        stats = _make_stats()
        result = format_stats_table(stats)
        assert _TICKET in result

    def test_contains_header_columns(self):
        stats = _make_stats()
        result = format_stats_table(stats)
        assert "Stage" in result
        assert "Iterations" in result
        assert "Machine Time" in result
        assert "Tokens In" in result
        assert "Tokens Out" in result

    def test_contains_totals_row(self):
        stats = _make_stats()
        result = format_stats_table(stats)
        assert "TOTAL" in result

    def test_contains_outcome(self):
        stats = _make_stats(outcome="Completed")
        result = format_stats_table(stats)
        assert "Completed" in result

    def test_contains_ci_cycles(self):
        stats = _make_stats(ci_cycles=3)
        result = format_stats_table(stats)
        assert "3" in result

    def test_run_id_included_when_present(self):
        stats = _make_stats(workflow_run_id="abc-123-def")
        result = format_stats_table(stats)
        assert "abc-123-def" in result

    def test_run_id_omitted_when_empty(self):
        stats = _make_stats(workflow_run_id="")
        result = format_stats_table(stats)
        assert "Run ID" not in result

    def test_workflow_statistics_heading(self):
        stats = _make_stats()
        result = format_stats_table(stats)
        assert "Workflow Statistics" in result


# ---------------------------------------------------------------------------
# format_stats_table — unexecuted stages
# ---------------------------------------------------------------------------


class TestFormatStatsTableUnexecutedStages:
    def test_empty_stages_shows_dashes(self):
        stats = _make_stats(stages={})
        result = format_stats_table(stats)
        # All feature stages should show dash
        assert _DASH in result

    def test_feature_stages_with_one_executed(self):
        stats = _make_stats(stages={"prd": _make_stage()})
        result = format_stats_table(stats)
        # PRD shows metrics; other stages show dashes
        assert _DASH in result
        # PRD row should have "1m 0s" (machine_time_seconds=60)
        assert "1m 0s" in result

    def test_dash_present_for_each_unexecuted_stage(self):
        """For N unexecuted feature stages there should be multiple dashes."""
        stats = _make_stats(stages={})
        result = format_stats_table(stats)
        count = result.count(_DASH)
        # 7 feature stages × 4 metric columns = 28 dashes
        assert count == 28


# ---------------------------------------------------------------------------
# format_stats_table — stage metrics accuracy
# ---------------------------------------------------------------------------


class TestFormatStatsTableMetrics:
    def test_iterations_displayed(self):
        stage = _make_stage(iteration_count=3)
        stats = _make_stats(stages={"prd": stage})
        result = format_stats_table(stats)
        assert "3" in result

    def test_machine_time_displayed(self):
        stage = _make_stage(machine_time_seconds=3661.0)
        stats = _make_stats(stages={"prd": stage})
        result = format_stats_table(stats)
        assert "1h 1m 1s" in result

    def test_input_tokens_displayed(self):
        stage = _make_stage(input_tokens=1_234_000)
        stats = _make_stats(stages={"prd": stage})
        result = format_stats_table(stats)
        assert "1,234,000" in result

    def test_output_tokens_displayed(self):
        stage = _make_stage(output_tokens=999)
        stats = _make_stats(stages={"prd": stage})
        result = format_stats_table(stats)
        assert "999" in result


# ---------------------------------------------------------------------------
# format_stats_table — summary totals
# ---------------------------------------------------------------------------


class TestFormatStatsTableTotals:
    def test_totals_row_sums_tokens(self):
        stages = {
            "prd": _make_stage(input_tokens=1000, output_tokens=500),
            "spec": _make_stage(input_tokens=2000, output_tokens=1000),
        }
        stats = _make_stats(stages=stages)
        result = format_stats_table(stats)
        # Total input = 3,000; total output = 1,500
        assert "3,000" in result
        assert "1,500" in result

    def test_totals_row_label(self):
        stats = _make_stats()
        result = format_stats_table(stats)
        assert "TOTAL" in result


# ---------------------------------------------------------------------------
# format_stats_table — PR links
# ---------------------------------------------------------------------------


class TestFormatStatsTablePrLinks:
    def test_pr_links_included_when_present(self):
        pr_url = "https://github.com/org/repo/pull/42"
        stats = _make_stats(pr_urls=[pr_url])
        result = format_stats_table(stats)
        assert pr_url in result
        assert "Pull Requests" in result

    def test_pr_links_omitted_when_empty(self):
        stats = _make_stats(pr_urls=[])
        result = format_stats_table(stats)
        assert "Pull Requests" not in result

    def test_multiple_pr_links(self):
        urls = [
            "https://github.com/org/repo/pull/1",
            "https://github.com/org/repo/pull/2",
        ]
        stats = _make_stats(pr_urls=urls)
        result = format_stats_table(stats)
        for url in urls:
            assert url in result


# ---------------------------------------------------------------------------
# format_stats_table — metadata
# ---------------------------------------------------------------------------


class TestFormatStatsTableMetadata:
    def test_started_from_earliest_stage(self):
        stages = {
            "prd": _make_stage(started_at="2024-01-01T01:00:00+00:00"),
            "spec": _make_stage(started_at="2024-01-01T00:00:00+00:00"),
        }
        stats = _make_stats(stages=stages)
        result = format_stats_table(stats)
        # Earliest started_at should appear as "Started"
        assert "2024-01-01T00:00:00+00:00" in result

    def test_last_updated_from_latest_ended(self):
        stages = {
            "prd": _make_stage(ended_at="2024-01-01T01:00:00+00:00"),
            "spec": _make_stage(ended_at="2024-01-01T02:00:00+00:00"),
        }
        stats = _make_stats(stages=stages)
        result = format_stats_table(stats)
        assert "2024-01-01T02:00:00+00:00" in result

    def test_started_omitted_when_no_stages(self):
        stats = _make_stats(stages={})
        result = format_stats_table(stats)
        assert "Started" not in result

    def test_outcome_reason_included(self):
        stats = _make_stats(outcome="Blocked", outcome_reason="Waiting for approval")
        result = format_stats_table(stats)
        assert "Waiting for approval" in result

    def test_outcome_reason_omitted_when_none(self):
        stats = _make_stats(outcome="Completed", outcome_reason=None)
        result = format_stats_table(stats)
        assert "Reason" not in result

    def test_outcome_reason_truncated(self):
        long_reason = "X" * 200
        stats = _make_stats(outcome="Failed", outcome_reason=long_reason)
        result = format_stats_table(stats)
        assert "..." in result
        # Reason line should exist and be truncated
        reason_line = [line for line in result.splitlines() if "Reason" in line][0]
        assert len(reason_line) < 200 + 20  # padded with label


# ---------------------------------------------------------------------------
# format_stats_table — outcome display
# ---------------------------------------------------------------------------


class TestFormatStatsTableOutcome:
    def test_in_progress_when_outcome_none(self):
        stats = _make_stats(outcome=None)
        result = format_stats_table(stats)
        assert "In Progress" in result

    def test_completed_outcome(self):
        stats = _make_stats(outcome="Completed")
        result = format_stats_table(stats)
        assert "Completed" in result

    def test_failed_outcome(self):
        stats = _make_stats(outcome="Failed: some error")
        result = format_stats_table(stats)
        assert "Failed" in result

    def test_blocked_outcome(self):
        stats = _make_stats(outcome="Blocked")
        result = format_stats_table(stats)
        assert "Blocked" in result


# ---------------------------------------------------------------------------
# format_stats_table — color support
# ---------------------------------------------------------------------------


class TestFormatStatsTableColor:
    def test_no_color_by_default(self):
        stats = _make_stats(outcome="Completed")
        result = format_stats_table(stats)
        assert "\033[" not in result

    def test_color_completed_green(self):
        stats = _make_stats(outcome="Completed")
        result = format_stats_table(stats, use_color=True)
        assert _COLOR_GREEN in result

    def test_color_failed_red(self):
        stats = _make_stats(outcome="Failed: err")
        result = format_stats_table(stats, use_color=True)
        assert _COLOR_RED in result

    def test_color_reset_present(self):
        stats = _make_stats(outcome="Completed")
        result = format_stats_table(stats, use_color=True)
        assert _COLOR_RESET in result


# ---------------------------------------------------------------------------
# format_stats_table — bug workflow stages
# ---------------------------------------------------------------------------


class TestFormatStatsTableBugWorkflow:
    def test_bug_stages_displayed(self):
        stages = {
            "triage": _make_stage(stage_name="triage"),
            "rca": _make_stage(stage_name="rca"),
        }
        stats = _make_stats(stages=stages)
        result = format_stats_table(stats)
        assert "Triage" in result
        assert "RCA" in result
        # Bug-specific stages
        assert "Planning" in result  # unexecuted but in bug list

    def test_bug_workflow_does_not_show_prd(self):
        """Bug workflows should not display PRD/Spec/Epics/Tasks stages."""
        stages = {"triage": _make_stage(stage_name="triage")}
        stats = _make_stats(stages=stages)
        result = format_stats_table(stats)
        assert "PRD" not in result
        assert "Epics" not in result


# ---------------------------------------------------------------------------
# format_stats_table — column width truncation
# ---------------------------------------------------------------------------


class TestFormatStatsTableColumnWidth:
    def test_long_values_truncated(self):
        """Very long values should be truncated to max_col_width."""
        stage = _make_stage(stage_name="implementation" * 5)  # absurdly long
        stats = _make_stats(stages={"implementation": stage})
        result = format_stats_table(stats, max_col_width=10)
        # No single cell should exceed the max width significantly
        for line in result.splitlines():
            if "|" in line:
                # Each cell within pipes should respect max width (with ...suffix)
                parts = [p.strip() for p in line.strip("|").split("|")]
                for part in parts:
                    assert len(part) <= 10 + 5  # allow some padding tolerance


# ---------------------------------------------------------------------------
# format_stats_json — basic validity
# ---------------------------------------------------------------------------


class TestFormatStatsJsonBasicValidity:
    def test_returns_string(self):
        stats = _make_stats()
        result = format_stats_json(stats)
        assert isinstance(result, str)

    def test_valid_json(self):
        stats = _make_stats()
        result = format_stats_json(stats)
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_pretty_printed(self):
        stats = _make_stats()
        result = format_stats_json(stats)
        # Pretty-printed JSON contains newlines and indentation
        assert "\n" in result
        assert "  " in result


# ---------------------------------------------------------------------------
# format_stats_json — field presence and typing
# ---------------------------------------------------------------------------


class TestFormatStatsJsonFields:
    def setup_method(self):
        stage = _make_stage(
            stage_name="prd",
            iteration_count=2,
            machine_time_seconds=90.0,
            human_time_seconds=30.0,
            input_tokens=1000,
            output_tokens=500,
            started_at="2024-01-01T00:00:00+00:00",
            ended_at="2024-01-01T01:00:00+00:00",
        )
        self.stats = _make_stats(
            stages={"prd": stage},
            pr_urls=["https://github.com/org/repo/pull/1"],
            ci_cycles=2,
            outcome="Completed",
            outcome_reason=None,
            comment_posted=True,
            workflow_run_id="abc-123",
        )
        self.parsed = json.loads(format_stats_json(self.stats))

    def test_ticket_key_field(self):
        assert self.parsed["ticket_key"] == _TICKET

    def test_outcome_field(self):
        assert self.parsed["outcome"] == "Completed"

    def test_outcome_reason_field(self):
        assert self.parsed["outcome_reason"] is None

    def test_ci_cycles_field(self):
        assert self.parsed["ci_cycles"] == 2

    def test_comment_posted_field(self):
        assert self.parsed["comment_posted"] is True

    def test_workflow_run_id_field(self):
        assert self.parsed["workflow_run_id"] == "abc-123"

    def test_pr_urls_field(self):
        assert self.parsed["pr_urls"] == ["https://github.com/org/repo/pull/1"]

    def test_stages_field_present(self):
        assert "stages" in self.parsed

    def test_stage_has_all_fields(self):
        prd = self.parsed["stages"]["prd"]
        assert "stage_name" in prd
        assert "iteration_count" in prd
        assert "machine_time_seconds" in prd
        assert "input_tokens" in prd
        assert "output_tokens" in prd
        assert "started_at" in prd
        assert "ended_at" in prd

    def test_stage_field_types(self):
        prd = self.parsed["stages"]["prd"]
        assert isinstance(prd["stage_name"], str)
        assert isinstance(prd["iteration_count"], int)
        assert isinstance(prd["machine_time_seconds"], float)
        assert isinstance(prd["input_tokens"], int)
        assert isinstance(prd["output_tokens"], int)
        assert isinstance(prd["started_at"], str)
        assert prd["ended_at"] is not None

    def test_stage_name_value(self):
        assert self.parsed["stages"]["prd"]["stage_name"] == "prd"

    def test_stage_metrics_values(self):
        prd = self.parsed["stages"]["prd"]
        assert prd["iteration_count"] == 2
        assert prd["input_tokens"] == 1000
        assert prd["output_tokens"] == 500


# ---------------------------------------------------------------------------
# format_stats_json — edge cases
# ---------------------------------------------------------------------------


class TestFormatStatsJsonEdgeCases:
    def test_empty_stages(self):
        stats = _make_stats(stages={})
        parsed = json.loads(format_stats_json(stats))
        assert parsed["stages"] == {}

    def test_none_outcome(self):
        stats = _make_stats(outcome=None)
        parsed = json.loads(format_stats_json(stats))
        assert parsed["outcome"] is None

    def test_empty_pr_urls(self):
        stats = _make_stats(pr_urls=[])
        parsed = json.loads(format_stats_json(stats))
        assert parsed["pr_urls"] == []

    def test_multiple_stages(self):
        stages = {
            "prd": _make_stage(stage_name="prd"),
            "spec": _make_stage(stage_name="spec"),
        }
        stats = _make_stats(stages=stages)
        parsed = json.loads(format_stats_json(stats))
        assert set(parsed["stages"].keys()) == {"prd", "spec"}

    def test_sorted_keys(self):
        stats = _make_stats(
            stages={"prd": _make_stage()},
            pr_urls=["https://example.com"],
            ci_cycles=1,
            outcome="Completed",
        )
        result = format_stats_json(stats)
        parsed_keys = list(json.loads(result).keys())
        assert parsed_keys == sorted(parsed_keys)

    def test_started_at_none_serialized(self):
        stage = _make_stage(started_at=None, ended_at=None)
        stats = _make_stats(stages={"prd": stage})
        parsed = json.loads(format_stats_json(stats))
        assert parsed["stages"]["prd"]["started_at"] is None
        assert parsed["stages"]["prd"]["ended_at"] is None

    def test_missing_stage_fields_use_defaults(self):
        """Stages with missing fields should use zero/None defaults."""
        stats = _make_stats(stages={"prd": {}})
        parsed = json.loads(format_stats_json(stats))
        prd = parsed["stages"]["prd"]
        assert prd["iteration_count"] == 0
        assert prd["machine_time_seconds"] == 0.0
        assert prd["input_tokens"] == 0
        assert prd["started_at"] is None
