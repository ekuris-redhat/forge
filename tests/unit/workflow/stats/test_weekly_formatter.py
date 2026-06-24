"""Unit tests for forge.workflow.stats.weekly_formatter.

Coverage:
- _format_duration: edge cases (0s, minutes, hours, > 24h)
- _format_token_count: abbreviation thresholds (raw, k, M)
- _format_bottleneck_section: all fields present/absent
- format_weekly_report_cli: structure, sections, empty lists, feature rollups
- format_weekly_report_markdown: valid markdown structure, tables, rollups
- format_weekly_report_json: valid parseable JSON, all fields, rollups
"""

from __future__ import annotations

import json

import pytest

from forge.workflow.stats.weekly_formatter import (
    _format_bottleneck_section,
    _format_duration,
    _format_token_count,
    format_weekly_report_cli,
    format_weekly_report_json,
    format_weekly_report_markdown,
)
from forge.workflow.stats.weekly_report import (
    UNASSIGNED_FEATURE_KEY,
    BottleneckAnalysis,
    FeatureRollup,
    TicketSummary,
    WeeklyReportData,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_ticket(
    ticket_key: str = "AISOS-1",
    ticket_type: str = "Feature",
    status: str = "completed",
    duration_seconds: float | None = 3600.0,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    ci_cycles: int = 0,
    outcome: str | None = "Completed",
) -> TicketSummary:
    return TicketSummary(
        ticket_key=ticket_key,
        ticket_type=ticket_type,
        status=status,
        duration_seconds=duration_seconds,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        ci_cycles=ci_cycles,
        outcome=outcome,
        tokens_by_stage={"prd": (input_tokens, output_tokens)},
        revision_counts={"prd": 1},
        stage_durations={"prd": duration_seconds or 0.0},
    )


def _make_report(
    project: str = "AISOS",
    period_days: int = 7,
    completed: list[TicketSummary] | None = None,
    in_progress: list[TicketSummary] | None = None,
    blocked: list[TicketSummary] | None = None,
    tokens_by_stage: dict | None = None,
    avg_cycle_time: float | None = None,
    bottlenecks: BottleneckAnalysis | None = None,
    feature_rollups: dict | None = None,
) -> WeeklyReportData:
    completed = completed or []
    in_progress = in_progress or []
    blocked = blocked or []
    all_tickets = completed + in_progress + blocked
    total_in = sum(t.input_tokens for t in all_tickets)
    total_out = sum(t.output_tokens for t in all_tickets)
    return WeeklyReportData(
        project=project,
        period_days=period_days,
        report_start="2024-06-08T00:00:00+00:00",
        report_end="2024-06-15T00:00:00+00:00",
        completed_tickets=completed,
        in_progress_tickets=in_progress,
        blocked_tickets=blocked,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        tokens_by_stage=tokens_by_stage or {},
        avg_cycle_time=avg_cycle_time,
        bottlenecks=bottlenecks or BottleneckAnalysis(),
        all_tickets=all_tickets,
        feature_rollups=feature_rollups or {},
    )


# ---------------------------------------------------------------------------
# Tests: _format_duration
# ---------------------------------------------------------------------------


class TestFormatDuration:
    def test_zero_seconds(self) -> None:
        assert _format_duration(0) == "0s"

    def test_sub_minute(self) -> None:
        assert _format_duration(45) == "45s"

    def test_exactly_one_minute(self) -> None:
        assert _format_duration(60) == "1m 0s"

    def test_minutes_and_seconds(self) -> None:
        assert _format_duration(90) == "1m 30s"

    def test_minutes_only(self) -> None:
        assert _format_duration(120) == "2m 0s"

    def test_exactly_one_hour(self) -> None:
        assert _format_duration(3600) == "1h 0m"

    def test_hours_and_minutes(self) -> None:
        assert _format_duration(3662) == "1h 1m"

    def test_large_hours_and_minutes(self) -> None:
        assert _format_duration(13320) == "3h 42m"

    def test_over_24_hours(self) -> None:
        # 25 hours + 1 minute
        assert _format_duration(90061) == "25h 1m"

    def test_fractional_seconds_truncated(self) -> None:
        # float with fractional part — truncated (not rounded)
        assert _format_duration(61.9) == "1m 1s"

    def test_exactly_one_hour_one_minute(self) -> None:
        assert _format_duration(3660) == "1h 1m"

    def test_seconds_only_large(self) -> None:
        assert _format_duration(59) == "59s"


# ---------------------------------------------------------------------------
# Tests: _format_token_count
# ---------------------------------------------------------------------------


class TestFormatTokenCount:
    def test_zero(self) -> None:
        assert _format_token_count(0) == "0"

    def test_below_1k(self) -> None:
        assert _format_token_count(999) == "999"

    def test_exactly_1k(self) -> None:
        assert _format_token_count(1000) == "1k"

    def test_1500_is_1_point_5k(self) -> None:
        assert _format_token_count(1500) == "1.5k"

    def test_31k(self) -> None:
        assert _format_token_count(31000) == "31k"

    def test_999k(self) -> None:
        assert _format_token_count(999000) == "999k"

    def test_exactly_1m(self) -> None:
        assert _format_token_count(1_000_000) == "1M"

    def test_1_5m(self) -> None:
        assert _format_token_count(1_500_000) == "1.5M"

    def test_10m(self) -> None:
        assert _format_token_count(10_000_000) == "10M"

    def test_2500_is_2_point_5k(self) -> None:
        assert _format_token_count(2500) == "2.5k"

    def test_500(self) -> None:
        assert _format_token_count(500) == "500"

    def test_round_thousands(self) -> None:
        assert _format_token_count(5000) == "5k"

    def test_2m_exact(self) -> None:
        assert _format_token_count(2_000_000) == "2M"


# ---------------------------------------------------------------------------
# Tests: _format_bottleneck_section
# ---------------------------------------------------------------------------


class TestFormatBottleneckSection:
    def test_empty_bottlenecks(self) -> None:
        b = BottleneckAnalysis()
        result = _format_bottleneck_section(b)
        assert "Tickets Analysed : 0" in result
        assert "Slowest Stage" in result
        assert "CI Fix Rate      : 0%" in result
        assert "Most Revised" in result

    def test_with_slowest_stage(self) -> None:
        b = BottleneckAnalysis(
            avg_stage_durations={"prd": 3600.0},
            slowest_stage="prd",
            total_tickets_analyzed=5,
        )
        result = _format_bottleneck_section(b)
        assert "PRD" in result
        assert "1h 0m" in result
        assert "Tickets Analysed : 5" in result

    def test_ci_fix_rate_percentage(self) -> None:
        b = BottleneckAnalysis(ci_fix_rate=0.4, total_tickets_analyzed=10)
        result = _format_bottleneck_section(b)
        assert "CI Fix Rate      : 40%" in result

    def test_ci_fix_rate_zero_percent(self) -> None:
        b = BottleneckAnalysis(ci_fix_rate=0.0)
        result = _format_bottleneck_section(b)
        assert "CI Fix Rate      : 0%" in result

    def test_ci_fix_rate_100_percent(self) -> None:
        b = BottleneckAnalysis(ci_fix_rate=1.0, total_tickets_analyzed=3)
        result = _format_bottleneck_section(b)
        assert "CI Fix Rate      : 100%" in result

    def test_most_revised_stages_top_3(self) -> None:
        b = BottleneckAnalysis(
            most_revised_stages=["prd", "spec", "implementation", "ci"],
        )
        result = _format_bottleneck_section(b)
        assert "PRD" in result
        assert "Spec" in result
        assert "Implementation" in result
        # 4th stage should NOT appear (top 3 only)
        assert "CI" not in result.split("Most Revised")[1].split("\n")[0]

    def test_most_revised_empty(self) -> None:
        b = BottleneckAnalysis(most_revised_stages=[])
        result = _format_bottleneck_section(b)
        assert "Most Revised" in result

    def test_avg_stage_durations_shown(self) -> None:
        b = BottleneckAnalysis(
            avg_stage_durations={"prd": 120.0, "spec": 240.0},
        )
        result = _format_bottleneck_section(b)
        assert "Stage Avg Durations" in result
        assert "PRD" in result
        assert "Spec" in result

    def test_no_avg_durations_no_subsection(self) -> None:
        b = BottleneckAnalysis(avg_stage_durations={})
        result = _format_bottleneck_section(b)
        assert "Stage Avg Durations" not in result

    def test_unknown_stage_key_title_cased(self) -> None:
        b = BottleneckAnalysis(
            avg_stage_durations={"custom_stage": 60.0},
            slowest_stage="custom_stage",
        )
        result = _format_bottleneck_section(b)
        assert "Custom_Stage" in result


# ---------------------------------------------------------------------------
# Tests: format_weekly_report_cli
# ---------------------------------------------------------------------------


class TestFormatWeeklyReportCli:
    def test_returns_string(self) -> None:
        report = _make_report()
        result = format_weekly_report_cli(report)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_header_contains_project(self) -> None:
        report = _make_report(project="MYPROJ")
        result = format_weekly_report_cli(report)
        assert "MYPROJ" in result

    def test_period_in_header(self) -> None:
        report = _make_report(period_days=14)
        result = format_weekly_report_cli(report)
        assert "14" in result

    def test_date_range_in_header(self) -> None:
        report = _make_report()
        result = format_weekly_report_cli(report)
        assert "2024-06-08" in result
        assert "2024-06-15" in result

    def test_summary_section_present(self) -> None:
        report = _make_report()
        result = format_weekly_report_cli(report)
        assert "Summary" in result
        assert "Total Tickets" in result
        assert "Avg Cycle Time" in result

    def test_ticket_counts_match(self) -> None:
        t1 = _make_ticket("AISOS-1", status="completed")
        t2 = _make_ticket("AISOS-2", status="in_progress")
        t3 = _make_ticket("AISOS-3", status="blocked")
        report = _make_report(completed=[t1], in_progress=[t2], blocked=[t3])
        result = format_weekly_report_cli(report)
        assert "Completed      : 1" in result
        assert "In Progress    : 1" in result
        assert "Blocked        : 1" in result
        assert "Total Tickets  : 3" in result

    def test_avg_cycle_time_shown(self) -> None:
        report = _make_report(avg_cycle_time=3600.0)
        result = format_weekly_report_cli(report)
        assert "1h 0m" in result

    def test_avg_cycle_time_none_shows_dash(self) -> None:
        report = _make_report(avg_cycle_time=None)
        result = format_weekly_report_cli(report)
        assert "Avg Cycle Time" in result
        assert "\u2014" in result  # em-dash

    def test_token_counts_shown(self) -> None:
        t1 = _make_ticket(input_tokens=31000, output_tokens=5000)
        report = _make_report(completed=[t1])
        result = format_weekly_report_cli(report)
        assert "Total Tokens" in result

    def test_completed_tickets_section(self) -> None:
        t1 = _make_ticket("AISOS-100")
        report = _make_report(completed=[t1])
        result = format_weekly_report_cli(report)
        assert "Completed Tickets" in result
        assert "AISOS-100" in result

    def test_empty_completed_shows_none(self) -> None:
        report = _make_report(completed=[])
        result = format_weekly_report_cli(report)
        assert "(none)" in result

    def test_in_progress_section(self) -> None:
        t = _make_ticket("AISOS-200", status="in_progress")
        report = _make_report(in_progress=[t])
        result = format_weekly_report_cli(report)
        assert "In-Progress Tickets" in result
        assert "AISOS-200" in result

    def test_blocked_section(self) -> None:
        t = _make_ticket("AISOS-300", status="blocked")
        report = _make_report(blocked=[t])
        result = format_weekly_report_cli(report)
        assert "Blocked Tickets" in result
        assert "AISOS-300" in result

    def test_token_by_stage_section(self) -> None:
        report = _make_report(tokens_by_stage={"prd": (1000, 500)})
        result = format_weekly_report_cli(report)
        assert "Token Usage by Stage" in result
        assert "PRD" in result

    def test_bottleneck_section_present(self) -> None:
        report = _make_report()
        result = format_weekly_report_cli(report)
        assert "Bottleneck Analysis" in result

    def test_feature_rollup_included_when_present(self) -> None:
        rollup = FeatureRollup(
            feature_key="AISOS-10",
            feature_summary="My Feature",
            linked_tickets=[_make_ticket("AISOS-11")],
            total_input_tokens=1000,
            total_output_tokens=500,
            tickets_completed=1,
            tickets_in_progress=0,
            completion_percentage=100.0,
        )
        report = _make_report(feature_rollups={"AISOS-10": rollup})
        result = format_weekly_report_cli(report)
        assert "Feature Rollup" in result
        assert "AISOS-10" in result
        assert "My Feature" in result

    def test_no_feature_rollup_section_when_empty(self) -> None:
        report = _make_report(feature_rollups={})
        result = format_weekly_report_cli(report)
        assert "Feature Rollup" not in result

    def test_ticket_duration_in_list(self) -> None:
        t = _make_ticket(duration_seconds=7380.0)  # 2h 3m
        report = _make_report(completed=[t])
        result = format_weekly_report_cli(report)
        assert "2h 3m" in result

    def test_ticket_duration_none_shown_as_dash(self) -> None:
        t = _make_ticket(duration_seconds=None)
        report = _make_report(completed=[t])
        result = format_weekly_report_cli(report)
        assert "\u2014" in result

    def test_total_tokens_abbreviated(self) -> None:
        t = _make_ticket(input_tokens=500_000, output_tokens=500_000)
        report = _make_report(completed=[t])
        result = format_weekly_report_cli(report)
        assert "1M" in result or "1000k" not in result  # abbreviated

    def test_unassigned_feature_rollup(self) -> None:
        rollup = FeatureRollup(
            feature_key=UNASSIGNED_FEATURE_KEY,
            feature_summary="",
            linked_tickets=[],
        )
        report = _make_report(feature_rollups={UNASSIGNED_FEATURE_KEY: rollup})
        result = format_weekly_report_cli(report)
        assert UNASSIGNED_FEATURE_KEY in result


# ---------------------------------------------------------------------------
# Tests: format_weekly_report_markdown
# ---------------------------------------------------------------------------


class TestFormatWeeklyReportMarkdown:
    def test_returns_string(self) -> None:
        report = _make_report()
        result = format_weekly_report_markdown(report)
        assert isinstance(result, str)

    def test_h1_header_contains_project(self) -> None:
        report = _make_report(project="TESTPROJ")
        result = format_weekly_report_markdown(report)
        assert "# Weekly Report" in result
        assert "TESTPROJ" in result

    def test_h2_sections_present(self) -> None:
        report = _make_report()
        result = format_weekly_report_markdown(report)
        assert "## Summary" in result
        assert "## Completed Tickets" in result
        assert "## In-Progress Tickets" in result
        assert "## Blocked Tickets" in result
        assert "## Token Usage by Stage" in result
        assert "## Bottleneck Analysis" in result

    def test_summary_table_has_rows(self) -> None:
        t = _make_ticket()
        report = _make_report(completed=[t])
        result = format_weekly_report_markdown(report)
        assert "| Total Tickets |" in result
        assert "| Completed |" in result

    def test_completed_tickets_table(self) -> None:
        t = _make_ticket("AISOS-1")
        report = _make_report(completed=[t])
        result = format_weekly_report_markdown(report)
        assert "| Ticket | Type | Duration | Tokens |" in result
        assert "| AISOS-1 |" in result

    def test_empty_completed_shows_italic_none(self) -> None:
        report = _make_report(completed=[])
        result = format_weekly_report_markdown(report)
        assert "_No completed tickets this period._" in result

    def test_empty_in_progress_shows_italic_none(self) -> None:
        report = _make_report(in_progress=[])
        result = format_weekly_report_markdown(report)
        assert "_No in-progress tickets this period._" in result

    def test_empty_blocked_shows_italic_none(self) -> None:
        report = _make_report(blocked=[])
        result = format_weekly_report_markdown(report)
        assert "_No blocked tickets this period._" in result

    def test_token_usage_table_with_data(self) -> None:
        report = _make_report(tokens_by_stage={"prd": (1000, 500), "spec": (2000, 800)})
        result = format_weekly_report_markdown(report)
        assert "| Stage | Input | Output | Total |" in result
        assert "| PRD |" in result
        assert "| Spec |" in result

    def test_no_token_data_shows_message(self) -> None:
        report = _make_report(tokens_by_stage={})
        result = format_weekly_report_markdown(report)
        assert "_No stage token data available._" in result

    def test_bottleneck_table_present(self) -> None:
        report = _make_report(
            bottlenecks=BottleneckAnalysis(
                total_tickets_analyzed=5,
                ci_fix_rate=0.4,
                slowest_stage="prd",
                avg_stage_durations={"prd": 3600.0},
            )
        )
        result = format_weekly_report_markdown(report)
        assert "| Tickets Analysed |" in result
        assert "| CI Fix Rate |" in result
        assert "40%" in result

    def test_feature_rollup_section_included(self) -> None:
        rollup = FeatureRollup(
            feature_key="AISOS-10",
            feature_summary="My Feature",
            linked_tickets=[_make_ticket("AISOS-11")],
            total_input_tokens=5000,
            total_output_tokens=2000,
            tickets_completed=1,
            tickets_in_progress=0,
            completion_percentage=100.0,
        )
        report = _make_report(feature_rollups={"AISOS-10": rollup})
        result = format_weekly_report_markdown(report)
        assert "## Feature Rollup" in result
        assert "| AISOS-10 |" in result
        assert "My Feature" in result

    def test_no_feature_rollup_section_when_empty(self) -> None:
        report = _make_report(feature_rollups={})
        result = format_weekly_report_markdown(report)
        assert "## Feature Rollup" not in result

    def test_markdown_table_separator_present(self) -> None:
        report = _make_report()
        result = format_weekly_report_markdown(report)
        # All tables should have separator rows with |---|
        assert "|--------|-------|" in result

    def test_avg_cycle_time_in_summary(self) -> None:
        report = _make_report(avg_cycle_time=7200.0)
        result = format_weekly_report_markdown(report)
        assert "2h 0m" in result

    def test_stage_avg_durations_subsection(self) -> None:
        b = BottleneckAnalysis(
            avg_stage_durations={"prd": 3600.0},
            slowest_stage="prd",
        )
        report = _make_report(bottlenecks=b)
        result = format_weekly_report_markdown(report)
        assert "### Stage Average Durations" in result
        assert "| PRD |" in result

    def test_period_days_in_header(self) -> None:
        report = _make_report(period_days=30)
        result = format_weekly_report_markdown(report)
        assert "Last 30 Days" in result

    def test_date_range_present(self) -> None:
        report = _make_report()
        result = format_weekly_report_markdown(report)
        assert "2024-06-08" in result
        assert "2024-06-15" in result

    def test_completion_percentage_in_rollup(self) -> None:
        rollup = FeatureRollup(
            feature_key="F-1",
            linked_tickets=[_make_ticket("T-1")],
            tickets_completed=1,
            tickets_in_progress=0,
            completion_percentage=66.7,
        )
        report = _make_report(feature_rollups={"F-1": rollup})
        result = format_weekly_report_markdown(report)
        assert "67%" in result

    def test_ticket_type_in_table(self) -> None:
        t = _make_ticket("BUG-1", ticket_type="Bug", status="completed")
        report = _make_report(completed=[t])
        result = format_weekly_report_markdown(report)
        assert "Bug" in result


# ---------------------------------------------------------------------------
# Tests: format_weekly_report_json
# ---------------------------------------------------------------------------


class TestFormatWeeklyReportJson:
    def test_returns_valid_json(self) -> None:
        report = _make_report()
        result = format_weekly_report_json(report)
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_top_level_keys_present(self) -> None:
        report = _make_report()
        parsed = json.loads(format_weekly_report_json(report))
        required_keys = {
            "project",
            "period_days",
            "report_start",
            "report_end",
            "summary",
            "tokens_by_stage",
            "bottlenecks",
            "completed_tickets",
            "in_progress_tickets",
            "blocked_tickets",
            "feature_rollups",
        }
        assert required_keys.issubset(parsed.keys())

    def test_project_name_in_json(self) -> None:
        report = _make_report(project="MYPROJ")
        parsed = json.loads(format_weekly_report_json(report))
        assert parsed["project"] == "MYPROJ"

    def test_period_days_in_json(self) -> None:
        report = _make_report(period_days=14)
        parsed = json.loads(format_weekly_report_json(report))
        assert parsed["period_days"] == 14

    def test_summary_section_structure(self) -> None:
        t = _make_ticket()
        report = _make_report(completed=[t])
        parsed = json.loads(format_weekly_report_json(report))
        summary = parsed["summary"]
        assert "total_tickets" in summary
        assert "completed" in summary
        assert "in_progress" in summary
        assert "blocked" in summary
        assert "avg_cycle_time_seconds" in summary
        assert "total_input_tokens" in summary
        assert "total_output_tokens" in summary

    def test_completed_count_in_summary(self) -> None:
        t1 = _make_ticket("T1")
        t2 = _make_ticket("T2")
        report = _make_report(completed=[t1, t2])
        parsed = json.loads(format_weekly_report_json(report))
        assert parsed["summary"]["completed"] == 2
        assert parsed["summary"]["total_tickets"] == 2

    def test_ticket_dict_fields(self) -> None:
        t = _make_ticket("AISOS-5", input_tokens=2000, output_tokens=800)
        report = _make_report(completed=[t])
        parsed = json.loads(format_weekly_report_json(report))
        ticket = parsed["completed_tickets"][0]
        assert ticket["ticket_key"] == "AISOS-5"
        assert ticket["input_tokens"] == 2000
        assert ticket["output_tokens"] == 800
        assert "status" in ticket
        assert "duration_seconds" in ticket
        assert "ci_cycles" in ticket
        assert "outcome" in ticket
        assert "tokens_by_stage" in ticket
        assert "revision_counts" in ticket
        assert "stage_durations" in ticket

    def test_tokens_by_stage_in_json(self) -> None:
        report = _make_report(tokens_by_stage={"prd": (1000, 500)})
        parsed = json.loads(format_weekly_report_json(report))
        assert "prd" in parsed["tokens_by_stage"]
        assert parsed["tokens_by_stage"]["prd"]["input"] == 1000
        assert parsed["tokens_by_stage"]["prd"]["output"] == 500

    def test_bottlenecks_section(self) -> None:
        b = BottleneckAnalysis(
            avg_stage_durations={"prd": 120.0},
            most_revised_stages=["prd", "spec"],
            ci_fix_rate=0.5,
            slowest_stage="prd",
            total_tickets_analyzed=10,
        )
        report = _make_report(bottlenecks=b)
        parsed = json.loads(format_weekly_report_json(report))
        bn = parsed["bottlenecks"]
        assert bn["total_tickets_analyzed"] == 10
        assert bn["slowest_stage"] == "prd"
        assert bn["ci_fix_rate"] == pytest.approx(0.5)
        assert bn["most_revised_stages"] == ["prd", "spec"]
        assert bn["avg_stage_durations"]["prd"] == pytest.approx(120.0)

    def test_feature_rollup_in_json(self) -> None:
        rollup = FeatureRollup(
            feature_key="AISOS-10",
            feature_summary="Feature Summary",
            linked_tickets=[_make_ticket("AISOS-11")],
            total_input_tokens=5000,
            total_output_tokens=2000,
            tickets_completed=1,
            tickets_in_progress=0,
            completion_percentage=100.0,
        )
        report = _make_report(feature_rollups={"AISOS-10": rollup})
        parsed = json.loads(format_weekly_report_json(report))
        assert "AISOS-10" in parsed["feature_rollups"]
        fr = parsed["feature_rollups"]["AISOS-10"]
        assert fr["feature_key"] == "AISOS-10"
        assert fr["feature_summary"] == "Feature Summary"
        assert fr["total_input_tokens"] == 5000
        assert fr["total_output_tokens"] == 2000
        assert fr["tickets_completed"] == 1
        assert fr["completion_percentage"] == pytest.approx(100.0)
        assert "AISOS-11" in fr["linked_tickets"]

    def test_empty_feature_rollups_is_empty_dict(self) -> None:
        report = _make_report(feature_rollups={})
        parsed = json.loads(format_weekly_report_json(report))
        assert parsed["feature_rollups"] == {}

    def test_avg_cycle_time_none_serialized(self) -> None:
        report = _make_report(avg_cycle_time=None)
        parsed = json.loads(format_weekly_report_json(report))
        assert parsed["summary"]["avg_cycle_time_seconds"] is None

    def test_avg_cycle_time_value_serialized(self) -> None:
        report = _make_report(avg_cycle_time=7200.0)
        parsed = json.loads(format_weekly_report_json(report))
        assert parsed["summary"]["avg_cycle_time_seconds"] == pytest.approx(7200.0)

    def test_output_is_sorted_keys(self) -> None:
        report = _make_report()
        result = format_weekly_report_json(report)
        parsed = json.loads(result)
        keys = list(parsed.keys())
        assert keys == sorted(keys)

    def test_in_progress_tickets_list(self) -> None:
        t = _make_ticket("AISOS-99", status="in_progress")
        report = _make_report(in_progress=[t])
        parsed = json.loads(format_weekly_report_json(report))
        assert len(parsed["in_progress_tickets"]) == 1
        assert parsed["in_progress_tickets"][0]["ticket_key"] == "AISOS-99"

    def test_blocked_tickets_list(self) -> None:
        t = _make_ticket("AISOS-88", status="blocked")
        report = _make_report(blocked=[t])
        parsed = json.loads(format_weekly_report_json(report))
        assert len(parsed["blocked_tickets"]) == 1
        assert parsed["blocked_tickets"][0]["ticket_key"] == "AISOS-88"

    def test_multiple_tickets_in_json(self) -> None:
        c1 = _make_ticket("AISOS-1")
        c2 = _make_ticket("AISOS-2")
        ip = _make_ticket("AISOS-3", status="in_progress")
        report = _make_report(completed=[c1, c2], in_progress=[ip])
        parsed = json.loads(format_weekly_report_json(report))
        assert parsed["summary"]["total_tickets"] == 3
        assert len(parsed["completed_tickets"]) == 2
        assert len(parsed["in_progress_tickets"]) == 1

    def test_token_raw_integers_not_abbreviated(self) -> None:
        """JSON should contain raw int values, not abbreviated strings like '1k'."""
        t = _make_ticket(input_tokens=31_000, output_tokens=5_000)
        report = _make_report(completed=[t])
        parsed = json.loads(format_weekly_report_json(report))
        assert parsed["completed_tickets"][0]["input_tokens"] == 31_000
        assert parsed["completed_tickets"][0]["output_tokens"] == 5_000

    def test_report_dates_preserved(self) -> None:
        report = _make_report()
        parsed = json.loads(format_weekly_report_json(report))
        assert parsed["report_start"] == "2024-06-08T00:00:00+00:00"
        assert parsed["report_end"] == "2024-06-15T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Tests: import paths
# ---------------------------------------------------------------------------


class TestImportPaths:
    def test_format_duration_importable(self) -> None:
        from forge.workflow.stats.weekly_formatter import _format_duration

        assert callable(_format_duration)

    def test_format_token_count_importable(self) -> None:
        from forge.workflow.stats.weekly_formatter import _format_token_count

        assert callable(_format_token_count)

    def test_format_bottleneck_section_importable(self) -> None:
        from forge.workflow.stats.weekly_formatter import _format_bottleneck_section

        assert callable(_format_bottleneck_section)

    def test_cli_formatter_importable(self) -> None:
        from forge.workflow.stats.weekly_formatter import format_weekly_report_cli

        assert callable(format_weekly_report_cli)

    def test_markdown_formatter_importable(self) -> None:
        from forge.workflow.stats.weekly_formatter import format_weekly_report_markdown

        assert callable(format_weekly_report_markdown)

    def test_json_formatter_importable(self) -> None:
        from forge.workflow.stats.weekly_formatter import format_weekly_report_json

        assert callable(format_weekly_report_json)
