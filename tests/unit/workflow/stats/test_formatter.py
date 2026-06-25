"""Unit tests for forge.workflow.stats.formatter.

All tests target format_stats_summary() and its internal helpers.
The suite is designed to achieve 100% branch coverage.
"""

from forge.workflow.stats.formatter import (
    _build_outcome_str,
    _build_stage_row,
    _build_totals_row,
    _fmt_seconds,
    _fmt_tokens,
    _truncate,
    format_stats_summary,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

#: A minimal pricing table used by cost-related tests.
_SAMPLE_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "claude-opus-4": {"input": 15.00, "output": 75.00},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
}


def _make_stage(
    *,
    stage_name: str = "prd",
    iteration_count: int = 1,
    machine_time_seconds: float = 60.0,
    human_time_seconds: float = 30.0,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    started_at: str | None = "2024-01-01T00:00:00+00:00",
    ended_at: str | None = "2024-01-01T00:01:00+00:00",
    model_name: str | None = None,
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
        "model_name": model_name,
    }


def _minimal_stats(**overrides) -> dict:
    """Return a minimal StatsState-like dict."""
    base = {
        "stage_timestamps": {},
        "stats_pr_urls": [],
        "stats_ci_cycles": 0,
        "workflow_outcome": None,
        "stats_outcome_reason": None,
        "stats_comment_posted": False,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short_string_unchanged(self):
        assert _truncate("hello") == "hello"

    def test_exactly_max_len_unchanged(self):
        text = "x" * 200
        assert _truncate(text) == text

    def test_one_over_max_len_truncated(self):
        text = "x" * 201
        result = _truncate(text)
        assert result == "x" * 200 + "..."
        assert len(result) == 203  # 200 chars + "..."

    def test_much_longer_text_truncated(self):
        text = "a" * 500
        result = _truncate(text)
        assert result.endswith("...")
        assert len(result) == 203

    def test_custom_max_len(self):
        result = _truncate("hello world", max_len=5)
        assert result == "hello..."

    def test_empty_string(self):
        assert _truncate("") == ""


# ---------------------------------------------------------------------------
# _fmt_seconds
# ---------------------------------------------------------------------------


class TestFmtSeconds:
    def test_seconds_only(self):
        assert _fmt_seconds(45.0) == "45s"

    def test_zero_seconds(self):
        assert _fmt_seconds(0.0) == "0s"

    def test_minutes_and_seconds(self):
        assert _fmt_seconds(90.0) == "1m 30s"

    def test_exact_minutes(self):
        assert _fmt_seconds(120.0) == "2m 0s"

    def test_hours_minutes_seconds(self):
        assert _fmt_seconds(3661.0) == "1h 1m 1s"

    def test_exact_hour(self):
        assert _fmt_seconds(3600.0) == "1h 0m 0s"

    def test_fractional_seconds_truncated(self):
        # Float fractions are discarded (int conversion)
        assert _fmt_seconds(90.9) == "1m 30s"

    def test_multiple_hours(self):
        assert _fmt_seconds(7322.0) == "2h 2m 2s"


# ---------------------------------------------------------------------------
# _fmt_tokens
# ---------------------------------------------------------------------------


class TestFmtTokens:
    def test_zero(self):
        assert _fmt_tokens(0) == "0"

    def test_small_number(self):
        assert _fmt_tokens(999) == "999"

    def test_thousands(self):
        assert _fmt_tokens(1000) == "1,000"

    def test_millions(self):
        assert _fmt_tokens(1_500_000) == "1,500,000"


# ---------------------------------------------------------------------------
# _build_stage_row
# ---------------------------------------------------------------------------


class TestBuildStageRow:
    def test_none_stage_shows_dashes(self):
        row = _build_stage_row("PRD", None)
        # Should show em-dash in all metric columns, with spaces
        assert "PRD" in row
        assert "—" in row
        # 6 dash columns (Iterations, Machine Time, Human Time, Input, Output, Cost)
        assert row.count("—") == 6

    def test_none_stage_has_spacing(self):
        row = _build_stage_row("PRD", None)
        assert row.startswith("| PRD |")

    def test_executed_stage_shows_metrics(self):
        stage = _make_stage(
            iteration_count=2,
            machine_time_seconds=90.0,
            human_time_seconds=60.0,
            input_tokens=1000,
            output_tokens=500,
        )
        row = _build_stage_row("PRD", stage)
        assert "| PRD |" in row
        assert "| 2 |" in row
        assert "| 1m 30s |" in row
        assert "| 1m 0s |" in row
        assert "| 1,000 |" in row
        assert "| 500 |" in row

    def test_executed_stage_no_pricing_shows_cost_unavailable(self):
        stage = _make_stage(input_tokens=1000, output_tokens=500)
        row = _build_stage_row("PRD", stage)
        assert "cost unavailable" in row

    def test_executed_stage_with_pricing_known_model(self):
        stage = _make_stage(
            model_name="claude-sonnet-4-5@20250929",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        row = _build_stage_row("PRD", stage, pricing=_SAMPLE_PRICING)
        # input: 1MTok * $3 = $3.00, output: 1MTok * $15 = $15.00, total = $18.00
        assert "$18.00" in row

    def test_executed_stage_with_pricing_unknown_model(self):
        stage = _make_stage(
            model_name="unknown-model-xyz",
            input_tokens=1000,
            output_tokens=500,
        )
        row = _build_stage_row("PRD", stage, pricing=_SAMPLE_PRICING)
        assert "cost unavailable" in row

    def test_executed_stage_with_pricing_no_model(self):
        stage = _make_stage(model_name=None, input_tokens=1000, output_tokens=500)
        row = _build_stage_row("PRD", stage, pricing=_SAMPLE_PRICING)
        assert "cost unavailable" in row

    def test_stage_with_zero_times(self):
        stage = _make_stage(
            iteration_count=1,
            machine_time_seconds=0.0,
            human_time_seconds=0.0,
            input_tokens=0,
            output_tokens=0,
        )
        row = _build_stage_row("Spec", stage)
        assert "| Spec |" in row
        assert "| 0s |" in row


# ---------------------------------------------------------------------------
# _build_totals_row
# ---------------------------------------------------------------------------


class TestBuildTotalsRow:
    def test_empty_stages(self):
        row = _build_totals_row({})
        assert "| *Total* |" in row
        assert "*0*" in row

    def test_single_stage(self):
        stages = {"prd": _make_stage(input_tokens=100, output_tokens=50)}
        row = _build_totals_row(stages)
        assert "*100*" in row
        assert "*50*" in row

    def test_multiple_stages_summed(self):
        stages = {
            "prd": _make_stage(input_tokens=1000, output_tokens=500),
            "spec": _make_stage(input_tokens=2000, output_tokens=800),
        }
        row = _build_totals_row(stages)
        assert "*3,000*" in row
        assert "*1,300*" in row

    def test_no_pricing_shows_cost_unavailable(self):
        stages = {"prd": _make_stage(input_tokens=100, output_tokens=50)}
        row = _build_totals_row(stages)
        assert "cost unavailable" in row

    def test_pricing_all_known_models(self):
        stages = {
            "prd": _make_stage(
                model_name="claude-sonnet-4-5@20250929",
                input_tokens=1_000_000,
                output_tokens=1_000_000,
            ),
        }
        row = _build_totals_row(stages, pricing=_SAMPLE_PRICING)
        # input: $3.00, output: $15.00, total: $18.00
        assert "$18.00" in row

    def test_pricing_any_unknown_model_shows_unavailable(self):
        stages = {
            "prd": _make_stage(
                model_name="claude-sonnet-4-5@20250929",
                input_tokens=1000,
                output_tokens=500,
            ),
            "spec": _make_stage(
                model_name="unknown-model",
                input_tokens=1000,
                output_tokens=500,
            ),
        }
        row = _build_totals_row(stages, pricing=_SAMPLE_PRICING)
        assert "cost unavailable" in row

    def test_pricing_zero_token_stages_skipped(self):
        """Stages with zero tokens should not be counted as 'unknown model'."""
        stages = {
            "prd": _make_stage(
                model_name="claude-sonnet-4-5@20250929",
                input_tokens=1_000_000,
                output_tokens=0,
            ),
            "ci": _make_stage(
                model_name=None,
                input_tokens=0,
                output_tokens=0,
            ),
        }
        row = _build_totals_row(stages, pricing=_SAMPLE_PRICING)
        # ci has zero tokens so it is skipped; prd cost = $3.00
        assert "$3.00" in row

    def test_has_spacing(self):
        row = _build_totals_row({})
        assert "| *Total* |" in row


# ---------------------------------------------------------------------------
# _build_outcome_str
# ---------------------------------------------------------------------------


class TestBuildOutcomeStr:
    def test_completed_no_detail(self):
        assert _build_outcome_str("completed", None) == "Completed"

    def test_completed_case_insensitive(self):
        assert _build_outcome_str("Completed", None) == "Completed"
        assert _build_outcome_str("COMPLETED", None) == "Completed"

    def test_completed_ignores_detail(self):
        # For 'completed', outcome_detail should be ignored
        assert _build_outcome_str("completed", "some detail") == "Completed"

    def test_blocked_with_reason(self):
        result = _build_outcome_str("blocked", "Waiting for security review")
        assert result == "Blocked: Waiting for security review"

    def test_blocked_without_reason(self):
        assert _build_outcome_str("blocked", None) == "Blocked"

    def test_blocked_with_empty_reason(self):
        assert _build_outcome_str("blocked", "") == "Blocked"

    def test_blocked_truncates_long_reason(self):
        long_reason = "x" * 201
        result = _build_outcome_str("blocked", long_reason)
        assert result == "Blocked: " + "x" * 200 + "..."

    def test_failed_with_error(self):
        result = _build_outcome_str("failed", "Database connection timeout")
        assert result == "Failed: Database connection timeout"

    def test_failed_without_error(self):
        assert _build_outcome_str("failed", None) == "Failed"

    def test_failed_with_empty_error(self):
        assert _build_outcome_str("failed", "") == "Failed"

    def test_failed_truncates_long_error(self):
        long_error = "e" * 300
        result = _build_outcome_str("failed", long_error)
        assert result.startswith("Failed: ")
        assert result.endswith("...")
        # detail portion is 200 chars
        assert len(result) == len("Failed: ") + 200 + 3

    def test_unknown_outcome_no_detail(self):
        result = _build_outcome_str("aborted", None)
        assert result == "aborted"

    def test_unknown_outcome_with_detail(self):
        result = _build_outcome_str("aborted", "some reason")
        assert result == "aborted: some reason"


# ---------------------------------------------------------------------------
# format_stats_summary — structural / content tests
# ---------------------------------------------------------------------------


class TestFormatStatsSummaryStructure:
    def test_returns_string(self):
        result = format_stats_summary(_minimal_stats(), "completed")
        assert isinstance(result, str)

    def test_contains_header(self):
        result = format_stats_summary(_minimal_stats(), "completed")
        assert "h3. Workflow Statistics" in result

    def test_contains_table_header_row_with_spacing(self):
        result = format_stats_summary(_minimal_stats(), "completed")
        assert (
            "|| Stage || Iterations || Machine Time || Human Time ||"
            " Input Tokens || Output Tokens || Cost ||" in result
        )

    def test_contains_all_feature_stages(self):
        result = format_stats_summary(_minimal_stats(), "completed")
        for label in ["PRD", "Spec", "Epics", "Tasks", "Implementation", "CI", "Review"]:
            assert label in result

    def test_never_executed_stages_show_dash(self):
        result = format_stats_summary(_minimal_stats(), "completed")
        # All stages are unexecuted; each row should have em-dashes
        lines = result.splitlines()
        stage_rows = [
            line
            for line in lines
            if line.startswith("|")
            and not line.startswith("||")
            and not line.startswith("| *Total*")
        ]
        assert len(stage_rows) == 7  # 7 feature stages
        for row in stage_rows:
            assert "—" in row

    def test_contains_totals_row(self):
        result = format_stats_summary(_minimal_stats(), "completed")
        assert "| *Total* |" in result

    def test_contains_ci_cycles(self):
        stats = _minimal_stats(stats_ci_cycles=3)
        result = format_stats_summary(stats, "completed")
        assert "*CI Cycles:* 3" in result

    def test_contains_outcome(self):
        result = format_stats_summary(_minimal_stats(), "completed")
        assert "*Outcome:* Completed" in result


class TestFormatStatsSummaryPRLinks:
    def test_no_prs_omits_section(self):
        result = format_stats_summary(_minimal_stats(), "completed")
        assert "Pull Requests" not in result

    def test_single_pr_included(self):
        stats = _minimal_stats(stats_pr_urls=["https://github.com/org/repo/pull/1"])
        result = format_stats_summary(stats, "completed")
        assert "*Pull Requests*" in result
        assert "* [https://github.com/org/repo/pull/1|https://github.com/org/repo/pull/1]" in result

    def test_multiple_prs_all_included(self):
        urls = [
            "https://github.com/org/repo/pull/1",
            "https://github.com/org/repo/pull/2",
        ]
        stats = _minimal_stats(stats_pr_urls=urls)
        result = format_stats_summary(stats, "completed")
        assert "*Pull Requests*" in result
        for url in urls:
            assert f"* [{url}|{url}]" in result


class TestFormatStatsSummaryStageData:
    def test_executed_stage_shows_metrics(self):
        stage = _make_stage(
            stage_name="prd",
            iteration_count=3,
            machine_time_seconds=3661.0,
            human_time_seconds=120.0,
            input_tokens=5000,
            output_tokens=1500,
        )
        stats = _minimal_stats(stage_timestamps={"prd": stage})
        result = format_stats_summary(stats, "completed")
        assert "| PRD |" in result
        assert "| 3 |" in result
        assert "| 1h 1m 1s |" in result
        assert "| 2m 0s |" in result
        assert "| 5,000 |" in result
        assert "| 1,500 |" in result

    def test_unexecuted_stage_shows_dashes(self):
        stats = _minimal_stats()
        result = format_stats_summary(stats, "completed")
        assert "| PRD |" in result
        assert "—" in result

    def test_totals_sum_across_stages(self):
        stages = {
            "prd": _make_stage(input_tokens=1000, output_tokens=500),
            "spec": _make_stage(input_tokens=2000, output_tokens=800),
            "implementation": _make_stage(input_tokens=10000, output_tokens=4000),
        }
        stats = _minimal_stats(stage_timestamps=stages)
        result = format_stats_summary(stats, "completed")
        assert "*13,000*" in result
        assert "*5,300*" in result

    def test_empty_stages_totals_zero(self):
        result = format_stats_summary(_minimal_stats(), "completed")
        assert "*0*" in result


class TestFormatStatsSummaryOutcome:
    def test_completed_outcome(self):
        result = format_stats_summary(_minimal_stats(), "completed")
        assert "*Outcome:* Completed" in result

    def test_blocked_outcome_with_reason(self):
        result = format_stats_summary(
            _minimal_stats(),
            "blocked",
            outcome_detail="Waiting for approval",
        )
        assert "*Outcome:* Blocked: Waiting for approval" in result

    def test_blocked_outcome_no_reason(self):
        result = format_stats_summary(_minimal_stats(), "blocked")
        assert "*Outcome:* Blocked" in result

    def test_failed_outcome_with_error(self):
        result = format_stats_summary(
            _minimal_stats(),
            "failed",
            outcome_detail="Unhandled exception",
        )
        assert "*Outcome:* Failed: Unhandled exception" in result

    def test_failed_outcome_no_error(self):
        result = format_stats_summary(_minimal_stats(), "failed")
        assert "*Outcome:* Failed" in result

    def test_long_detail_truncated(self):
        long_reason = "z" * 300
        result = format_stats_summary(
            _minimal_stats(),
            "blocked",
            outcome_detail=long_reason,
        )
        expected_detail = "z" * 200 + "..."
        assert f"*Outcome:* Blocked: {expected_detail}" in result

    def test_exactly_200_char_detail_not_truncated(self):
        reason = "a" * 200
        result = format_stats_summary(_minimal_stats(), "blocked", outcome_detail=reason)
        assert f"*Outcome:* Blocked: {reason}" in result
        assert "..." not in result

    def test_outcome_case_insensitive(self):
        result = format_stats_summary(_minimal_stats(), "Completed")
        assert "*Outcome:* Completed" in result


class TestFormatStatsSummaryMissingFields:
    """Ensure the formatter handles states with missing optional fields gracefully."""

    def test_empty_state_dict(self):
        """A completely empty dict should produce valid output without errors."""
        result = format_stats_summary({}, "completed")
        assert isinstance(result, str)
        assert "*CI Cycles:* 0" in result
        assert "*Outcome:* Completed" in result

    def test_none_stage_timestamps(self):
        stats = _minimal_stats(stage_timestamps=None)
        result = format_stats_summary(stats, "completed")
        assert "| *Total* |" in result

    def test_none_pr_urls(self):
        stats = _minimal_stats(stats_pr_urls=None)
        result = format_stats_summary(stats, "completed")
        assert "Pull Requests" not in result

    def test_none_ci_cycles(self):
        stats = _minimal_stats(stats_ci_cycles=None)
        result = format_stats_summary(stats, "completed")
        assert "*CI Cycles:* 0" in result


# ---------------------------------------------------------------------------
# Cost column tests
# ---------------------------------------------------------------------------


class TestCostColumn:
    """Tests for the Cost column in the stage table."""

    def test_cost_column_in_header(self):
        result = format_stats_summary(_minimal_stats(), "completed")
        assert "|| Cost ||" in result

    def test_cost_unavailable_when_no_pricing(self):
        stage = _make_stage(
            model_name="claude-sonnet-4-5@20250929",
            input_tokens=1000,
            output_tokens=500,
        )
        stats = _minimal_stats(stage_timestamps={"prd": stage})
        result = format_stats_summary(stats, "completed")
        assert "cost unavailable" in result

    def test_cost_displayed_with_pricing(self):
        stage = _make_stage(
            stage_name="prd",
            model_name="claude-sonnet-4-5@20250929",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        stats = _minimal_stats(stage_timestamps={"prd": stage})
        result = format_stats_summary(stats, "completed", pricing=_SAMPLE_PRICING)
        # input: $3.00, output: $15.00, total per stage: $18.00
        assert "$18.00" in result

    def test_cost_unavailable_when_model_not_in_pricing(self):
        stage = _make_stage(
            stage_name="prd",
            model_name="unknown-model-xyz",
            input_tokens=1000,
            output_tokens=500,
        )
        stats = _minimal_stats(stage_timestamps={"prd": stage})
        result = format_stats_summary(stats, "completed", pricing=_SAMPLE_PRICING)
        assert "cost unavailable" in result

    def test_total_cost_sum_across_stages(self):
        stages = {
            "prd": _make_stage(
                model_name="claude-sonnet-4-5@20250929",
                input_tokens=1_000_000,
                output_tokens=0,
            ),
            "spec": _make_stage(
                model_name="claude-sonnet-4-5@20250929",
                input_tokens=1_000_000,
                output_tokens=0,
            ),
        }
        stats = _minimal_stats(stage_timestamps=stages)
        result = format_stats_summary(stats, "completed", pricing=_SAMPLE_PRICING)
        # Each stage: $3.00 input; total: $6.00
        assert "$6.00" in result


# ---------------------------------------------------------------------------
# Cost alert section (token-based)
# ---------------------------------------------------------------------------


def _stats_with_tokens(input_tokens: int, output_tokens: int) -> dict:
    """Return a stats dict with a single stage carrying the given token counts."""
    stage = _make_stage(
        stage_name="prd",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    return _minimal_stats(stage_timestamps={"prd": stage})


class TestCostAlert:
    """Tests for the token-based cost alert section in format_stats_summary."""

    # ------------------------------------------------------------------
    # Threshold exceeded — alert should appear
    # ------------------------------------------------------------------

    def test_alert_appears_when_tokens_exceed_threshold(self):
        stats = _stats_with_tokens(input_tokens=600_000, output_tokens=500_000)
        result = format_stats_summary(stats, "completed", token_threshold=1_000_000)
        assert "COST ALERT" in result

    def test_alert_includes_threshold_value(self):
        stats = _stats_with_tokens(input_tokens=600_000, output_tokens=500_000)
        result = format_stats_summary(stats, "completed", token_threshold=1_000_000)
        assert "1,000,000" in result

    def test_alert_includes_actual_usage(self):
        # total = 600_000 + 500_000 = 1_100_000
        stats = _stats_with_tokens(input_tokens=600_000, output_tokens=500_000)
        result = format_stats_summary(stats, "completed", token_threshold=1_000_000)
        assert "1,100,000" in result

    def test_alert_panel_markup_present(self):
        stats = _stats_with_tokens(input_tokens=800_000, output_tokens=300_000)
        result = format_stats_summary(stats, "completed", token_threshold=1_000_000)
        assert "{panel:" in result
        assert "{panel}" in result

    def test_alert_appears_after_outcome(self):
        """Cost alert should be appended after the outcome line."""
        stats = _stats_with_tokens(input_tokens=600_000, output_tokens=500_000)
        result = format_stats_summary(stats, "completed", token_threshold=1_000_000)
        outcome_pos = result.index("*Outcome:*")
        alert_pos = result.index("COST ALERT")
        assert alert_pos > outcome_pos

    def test_alert_with_multiple_stages(self):
        """Total is summed across all stages when checking threshold."""
        stages = {
            "prd": _make_stage(input_tokens=400_000, output_tokens=200_000),
            "spec": _make_stage(input_tokens=300_000, output_tokens=200_000),
        }
        stats = _minimal_stats(stage_timestamps=stages)
        result = format_stats_summary(stats, "completed", token_threshold=1_000_000)
        # total = 400k + 200k + 300k + 200k = 1_100_000 > 1_000_000
        assert "COST ALERT" in result

    def test_alert_exactly_one_over_threshold(self):
        """Alert triggers when total tokens are strictly greater than threshold."""
        stats = _stats_with_tokens(input_tokens=1_000_000, output_tokens=1)
        result = format_stats_summary(stats, "completed", token_threshold=1_000_000)
        assert "COST ALERT" in result

    # ------------------------------------------------------------------
    # Threshold not exceeded — no alert
    # ------------------------------------------------------------------

    def test_no_alert_when_tokens_equal_threshold(self):
        """No alert when total tokens exactly equal the threshold."""
        stats = _stats_with_tokens(input_tokens=500_000, output_tokens=500_000)
        result = format_stats_summary(stats, "completed", token_threshold=1_000_000)
        assert "COST ALERT" not in result

    def test_no_alert_when_tokens_under_threshold(self):
        stats = _stats_with_tokens(input_tokens=100_000, output_tokens=200_000)
        result = format_stats_summary(stats, "completed", token_threshold=1_000_000)
        assert "COST ALERT" not in result

    def test_no_alert_when_no_stages_ran(self):
        """Zero tokens should never trigger a cost alert."""
        result = format_stats_summary(
            _minimal_stats(),
            "completed",
            token_threshold=0,
        )
        # 0 > 0 is False so no alert
        assert "COST ALERT" not in result

    # ------------------------------------------------------------------
    # Threshold not configured — no alert
    # ------------------------------------------------------------------

    def test_no_alert_when_threshold_is_none(self):
        """No alert section when threshold is None (default)."""
        stats = _stats_with_tokens(input_tokens=5_000_000, output_tokens=5_000_000)
        result = format_stats_summary(stats, "completed")
        assert "COST ALERT" not in result

    def test_no_alert_when_threshold_is_none_explicit(self):
        """Explicitly passing None disables cost alerting."""
        stats = _stats_with_tokens(input_tokens=5_000_000, output_tokens=5_000_000)
        result = format_stats_summary(stats, "completed", token_threshold=None)
        assert "COST ALERT" not in result

    # ------------------------------------------------------------------
    # Alert content details
    # ------------------------------------------------------------------

    def test_alert_label_in_panel_title(self):
        stats = _stats_with_tokens(input_tokens=600_000, output_tokens=500_000)
        result = format_stats_summary(stats, "completed", token_threshold=1_000_000)
        assert "⚠️ COST ALERT" in result

    def test_alert_threshold_label_present(self):
        stats = _stats_with_tokens(input_tokens=600_000, output_tokens=500_000)
        result = format_stats_summary(stats, "completed", token_threshold=1_000_000)
        assert "*Threshold:*" in result

    def test_alert_actual_usage_label_present(self):
        stats = _stats_with_tokens(input_tokens=600_000, output_tokens=500_000)
        result = format_stats_summary(stats, "completed", token_threshold=1_000_000)
        assert "*Actual usage:*" in result


# ---------------------------------------------------------------------------
# Dollar-based cost alert tests
# ---------------------------------------------------------------------------


class TestDollarCostAlert:
    """Tests for dollar-threshold cost alerting in format_stats_summary."""

    def _stats_with_model(
        self,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict:
        stage = _make_stage(
            stage_name="prd",
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return _minimal_stats(stage_timestamps={"prd": stage})

    def test_dollar_alert_triggers_when_cost_exceeds_threshold(self):
        # claude-sonnet-4: $3/MTok input, $15/MTok output
        # 2M input = $6.00, 1M output = $15.00, total = $21.00 > $10.00
        stats = self._stats_with_model(
            "claude-sonnet-4-5@20250929",
            input_tokens=2_000_000,
            output_tokens=1_000_000,
        )
        result = format_stats_summary(
            stats,
            "completed",
            dollar_threshold=10.00,
            pricing=_SAMPLE_PRICING,
        )
        assert "COST ALERT" in result

    def test_dollar_alert_shows_dollar_amounts(self):
        stats = self._stats_with_model(
            "claude-sonnet-4-5@20250929",
            input_tokens=2_000_000,
            output_tokens=1_000_000,
        )
        result = format_stats_summary(
            stats,
            "completed",
            dollar_threshold=10.00,
            pricing=_SAMPLE_PRICING,
        )
        assert "$10.00" in result  # threshold
        assert "$21.00" in result  # actual cost

    def test_dollar_alert_not_triggered_when_cost_below_threshold(self):
        # $1.00 input cost, well below $100 threshold
        stats = self._stats_with_model(
            "claude-sonnet-4-5@20250929",
            input_tokens=333_333,
            output_tokens=0,
        )
        result = format_stats_summary(
            stats,
            "completed",
            dollar_threshold=100.00,
            pricing=_SAMPLE_PRICING,
        )
        assert "COST ALERT" not in result

    def test_dollar_alert_not_triggered_when_cost_equals_threshold(self):
        # exactly $3.00 input for 1M tokens, threshold = $3.00
        stats = self._stats_with_model(
            "claude-sonnet-4-5@20250929",
            input_tokens=1_000_000,
            output_tokens=0,
        )
        result = format_stats_summary(
            stats,
            "completed",
            dollar_threshold=3.00,
            pricing=_SAMPLE_PRICING,
        )
        assert "COST ALERT" not in result

    def test_dollar_alert_not_triggered_without_pricing(self):
        """Dollar threshold without pricing table should not trigger alert."""
        stats = self._stats_with_model(
            "claude-sonnet-4-5@20250929",
            input_tokens=10_000_000,
            output_tokens=10_000_000,
        )
        result = format_stats_summary(
            stats,
            "completed",
            dollar_threshold=0.01,
            pricing=None,
        )
        assert "COST ALERT" not in result

    def test_dollar_alert_not_triggered_when_cost_unavailable(self):
        """Dollar alert should not trigger if model is unknown (cost unavailable)."""
        stats = self._stats_with_model(
            "unknown-model",
            input_tokens=10_000_000,
            output_tokens=10_000_000,
        )
        result = format_stats_summary(
            stats,
            "completed",
            dollar_threshold=0.01,
            pricing=_SAMPLE_PRICING,
        )
        assert "COST ALERT" not in result

    def test_dollar_alert_takes_precedence_over_token_threshold(self):
        """When dollar_threshold is set, token_threshold should be ignored."""
        # Very large tokens but low cost -> token threshold would trigger, dollar won't
        stats = self._stats_with_model(
            "claude-sonnet-4-5@20250929",
            input_tokens=5_000_000,
            output_tokens=0,
        )
        result = format_stats_summary(
            stats,
            "completed",
            token_threshold=1_000_000,  # would trigger if dollar not set
            dollar_threshold=1000.00,  # well above $15.00 cost
            pricing=_SAMPLE_PRICING,
        )
        # Dollar threshold dominates; $15.00 < $1000.00 so no alert
        assert "COST ALERT" not in result

    def test_dollar_alert_uses_actual_cost_label(self):
        stats = self._stats_with_model(
            "claude-sonnet-4-5@20250929",
            input_tokens=2_000_000,
            output_tokens=1_000_000,
        )
        result = format_stats_summary(
            stats,
            "completed",
            dollar_threshold=10.00,
            pricing=_SAMPLE_PRICING,
        )
        assert "*Actual cost:*" in result
