"""Unit tests for forge.workflow.stats_utils."""

import pytest

from forge.workflow.stats_utils import (
    add_pr_url,
    increment_ci_cycle,
    increment_revision,
    record_stage_end,
    record_stage_start,
    record_tokens,
    set_outcome,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_state() -> dict:
    """Return a minimal state with stats fields unset (simulates fresh run)."""
    return {}


def _state_with_stage(stage_name: str, **overrides) -> dict:
    """Return a state that already has one stage entry."""
    stage = {
        "stage_name": stage_name,
        "iteration_count": 0,
        "machine_time_seconds": 0.0,
        "human_time_seconds": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "started_at": "2024-01-01T00:00:00+00:00",
        "ended_at": None,
    }
    stage.update(overrides)
    return {"stats_stages": {stage_name: stage}}


# ---------------------------------------------------------------------------
# record_stage_start
# ---------------------------------------------------------------------------


class TestRecordStageStart:
    def test_initialises_stage_with_timestamp(self):
        result = record_stage_start(_empty_state(), "implement")

        assert "stats_stages" in result
        stage = result["stats_stages"]["implement"]
        assert stage["started_at"] is not None
        assert "T" in stage["started_at"]  # ISO-8601

    def test_zeroed_numeric_metrics(self):
        result = record_stage_start(_empty_state(), "implement")
        stage = result["stats_stages"]["implement"]

        assert stage["iteration_count"] == 0
        assert stage["machine_time_seconds"] == 0.0
        assert stage["human_time_seconds"] == 0.0
        assert stage["input_tokens"] == 0
        assert stage["output_tokens"] == 0

    def test_ended_at_is_none_on_init(self):
        result = record_stage_start(_empty_state(), "implement")
        assert result["stats_stages"]["implement"]["ended_at"] is None

    def test_stage_name_recorded(self):
        result = record_stage_start(_empty_state(), "triage")
        assert result["stats_stages"]["triage"]["stage_name"] == "triage"

    def test_resets_ended_at_on_re_entry(self):
        """Re-entering a stage clears ended_at (marks it in-progress again)."""
        state = _state_with_stage("implement", ended_at="2024-01-01T01:00:00+00:00")
        result = record_stage_start(state, "implement")
        assert result["stats_stages"]["implement"]["ended_at"] is None

    def test_preserves_accumulated_metrics_on_re_entry(self):
        """Re-entering should not zero out previously accumulated tokens."""
        state = _state_with_stage(
            "implement",
            input_tokens=500,
            output_tokens=250,
            machine_time_seconds=30.0,
        )
        result = record_stage_start(state, "implement")
        stage = result["stats_stages"]["implement"]

        assert stage["input_tokens"] == 500
        assert stage["output_tokens"] == 250
        assert stage["machine_time_seconds"] == 30.0

    def test_handles_missing_stats_stages_key(self):
        """Works when state has no stats_stages key at all."""
        result = record_stage_start({}, "plan")
        assert "plan" in result["stats_stages"]

    def test_does_not_mutate_existing_stages(self):
        """Other stages in stats_stages are preserved."""
        state = _state_with_stage("triage")
        result = record_stage_start(state, "implement")

        assert "triage" in result["stats_stages"]
        assert "implement" in result["stats_stages"]

    def test_returns_only_stats_stages_key(self):
        result = record_stage_start(_empty_state(), "implement")
        assert list(result.keys()) == ["stats_stages"]


# ---------------------------------------------------------------------------
# record_stage_end
# ---------------------------------------------------------------------------


class TestRecordStageEnd:
    def test_sets_ended_at_timestamp(self):
        state = _state_with_stage("implement")
        result = record_stage_end(state, "implement", machine_time=60.0)

        assert result["stats_stages"]["implement"]["ended_at"] is not None

    def test_accumulates_machine_time(self):
        state = _state_with_stage("implement", machine_time_seconds=10.0)
        result = record_stage_end(state, "implement", machine_time=25.5)

        assert result["stats_stages"]["implement"]["machine_time_seconds"] == pytest.approx(35.5)

    def test_accumulates_human_time(self):
        state = _state_with_stage("implement", human_time_seconds=100.0)
        result = record_stage_end(state, "implement", machine_time=0.0, human_time=50.0)

        assert result["stats_stages"]["implement"]["human_time_seconds"] == pytest.approx(150.0)

    def test_human_time_defaults_to_zero(self):
        state = _state_with_stage("implement")
        result = record_stage_end(state, "implement", machine_time=10.0)

        assert result["stats_stages"]["implement"]["human_time_seconds"] == pytest.approx(0.0)

    def test_handles_non_existent_stage(self):
        """Calling on a stage that was never started should not raise."""
        result = record_stage_end(_empty_state(), "ghost_stage", machine_time=5.0)

        stage = result["stats_stages"]["ghost_stage"]
        assert stage["machine_time_seconds"] == pytest.approx(5.0)
        assert stage["ended_at"] is not None

    def test_returns_only_stats_stages_key(self):
        state = _state_with_stage("implement")
        result = record_stage_end(state, "implement", machine_time=1.0)
        assert list(result.keys()) == ["stats_stages"]


# ---------------------------------------------------------------------------
# record_tokens
# ---------------------------------------------------------------------------


class TestRecordTokens:
    def test_accumulates_input_tokens(self):
        state = _state_with_stage("implement", input_tokens=100)
        result = record_tokens(state, "implement", input_tokens=200, output_tokens=0)

        assert result["stats_stages"]["implement"]["input_tokens"] == 300

    def test_accumulates_output_tokens(self):
        state = _state_with_stage("implement", output_tokens=50)
        result = record_tokens(state, "implement", input_tokens=0, output_tokens=75)

        assert result["stats_stages"]["implement"]["output_tokens"] == 125

    def test_accumulates_both_simultaneously(self):
        state = _state_with_stage("implement", input_tokens=10, output_tokens=5)
        result = record_tokens(state, "implement", input_tokens=20, output_tokens=10)

        stage = result["stats_stages"]["implement"]
        assert stage["input_tokens"] == 30
        assert stage["output_tokens"] == 15

    def test_handles_non_existent_stage(self):
        """Should initialise a new stage entry if it does not exist."""
        result = record_tokens(_empty_state(), "new_stage", input_tokens=50, output_tokens=25)

        stage = result["stats_stages"]["new_stage"]
        assert stage["input_tokens"] == 50
        assert stage["output_tokens"] == 25

    def test_does_not_replace_tokens(self):
        """Calling twice should add, not replace."""
        state = _state_with_stage("implement")
        first = record_tokens(state, "implement", input_tokens=100, output_tokens=50)
        second = record_tokens(first, "implement", input_tokens=100, output_tokens=50)

        assert second["stats_stages"]["implement"]["input_tokens"] == 200
        assert second["stats_stages"]["implement"]["output_tokens"] == 100

    def test_returns_only_stats_stages_key(self):
        result = record_tokens(_empty_state(), "impl", input_tokens=1, output_tokens=1)
        assert list(result.keys()) == ["stats_stages"]


# ---------------------------------------------------------------------------
# increment_revision
# ---------------------------------------------------------------------------


class TestIncrementRevision:
    def test_increments_iteration_count_by_one(self):
        state = _state_with_stage("implement", iteration_count=2)
        result = increment_revision(state, "implement")

        assert result["stats_stages"]["implement"]["iteration_count"] == 3

    def test_starts_at_one_for_new_stage(self):
        result = increment_revision(_empty_state(), "plan")

        assert result["stats_stages"]["plan"]["iteration_count"] == 1

    def test_multiple_increments_accumulate(self):
        state = _empty_state()
        for _ in range(5):
            state = {**state, **increment_revision(state, "implement")}

        assert state["stats_stages"]["implement"]["iteration_count"] == 5

    def test_returns_only_stats_stages_key(self):
        result = increment_revision(_empty_state(), "triage")
        assert list(result.keys()) == ["stats_stages"]


# ---------------------------------------------------------------------------
# increment_ci_cycle
# ---------------------------------------------------------------------------


class TestIncrementCiCycle:
    def test_increments_counter_from_zero(self):
        result = increment_ci_cycle(_empty_state())
        assert result["stats_ci_cycles"] == 1

    def test_increments_existing_counter(self):
        state = {"stats_ci_cycles": 3}
        result = increment_ci_cycle(state)
        assert result["stats_ci_cycles"] == 4

    def test_handles_none_counter(self):
        state = {"stats_ci_cycles": None}
        result = increment_ci_cycle(state)
        assert result["stats_ci_cycles"] == 1

    def test_multiple_increments(self):
        state = _empty_state()
        for _ in range(7):
            state = {**state, **increment_ci_cycle(state)}

        assert state["stats_ci_cycles"] == 7

    def test_returns_only_stats_ci_cycles_key(self):
        result = increment_ci_cycle(_empty_state())
        assert list(result.keys()) == ["stats_ci_cycles"]


# ---------------------------------------------------------------------------
# add_pr_url
# ---------------------------------------------------------------------------


class TestAddPrUrl:
    def test_appends_url_to_empty_list(self):
        result = add_pr_url(_empty_state(), "https://github.com/org/repo/pull/1")
        assert result["stats_pr_urls"] == ["https://github.com/org/repo/pull/1"]

    def test_appends_to_existing_list(self):
        state = {"stats_pr_urls": ["https://github.com/org/repo/pull/1"]}
        result = add_pr_url(state, "https://github.com/org/repo/pull/2")

        assert result["stats_pr_urls"] == [
            "https://github.com/org/repo/pull/1",
            "https://github.com/org/repo/pull/2",
        ]

    def test_idempotent_no_duplicates(self):
        url = "https://github.com/org/repo/pull/1"
        state = {"stats_pr_urls": [url]}
        result = add_pr_url(state, url)

        assert result["stats_pr_urls"] == [url]
        assert len(result["stats_pr_urls"]) == 1

    def test_calling_twice_does_not_duplicate(self):
        url = "https://github.com/org/repo/pull/42"
        state = _empty_state()
        state = {**state, **add_pr_url(state, url)}
        state = {**state, **add_pr_url(state, url)}

        assert state["stats_pr_urls"].count(url) == 1

    def test_handles_none_pr_urls(self):
        state = {"stats_pr_urls": None}
        result = add_pr_url(state, "https://example.com/pr/1")
        assert result["stats_pr_urls"] == ["https://example.com/pr/1"]

    def test_returns_only_stats_pr_urls_key(self):
        result = add_pr_url(_empty_state(), "https://example.com/pr/1")
        assert list(result.keys()) == ["stats_pr_urls"]

    def test_preserves_order(self):
        urls = [f"https://example.com/pr/{i}" for i in range(5)]
        state = _empty_state()
        for url in urls:
            state = {**state, **add_pr_url(state, url)}

        assert state["stats_pr_urls"] == urls


# ---------------------------------------------------------------------------
# set_outcome
# ---------------------------------------------------------------------------


class TestSetOutcome:
    def test_sets_outcome(self):
        result = set_outcome(_empty_state(), "Completed")
        assert result["stats_outcome"] == "Completed"

    def test_sets_reason_when_provided(self):
        result = set_outcome(_empty_state(), "Blocked: awaiting review", "PR still open")
        assert result["stats_outcome"] == "Blocked: awaiting review"
        assert result["stats_outcome_reason"] == "PR still open"

    def test_reason_defaults_to_none(self):
        result = set_outcome(_empty_state(), "Completed")
        assert result["stats_outcome_reason"] is None

    def test_overwrites_previous_outcome(self):
        state = {"stats_outcome": "Blocked", "stats_outcome_reason": "old reason"}
        result = set_outcome(state, "Completed", None)

        assert result["stats_outcome"] == "Completed"
        assert result["stats_outcome_reason"] is None

    def test_returns_both_keys(self):
        result = set_outcome(_empty_state(), "Failed: timeout")
        assert set(result.keys()) == {"stats_outcome", "stats_outcome_reason"}

    @pytest.mark.parametrize("outcome", ["Completed", "Blocked: foo", "Failed: bar"])
    def test_conventional_outcome_values(self, outcome: str):
        result = set_outcome(_empty_state(), outcome)
        assert result["stats_outcome"] == outcome
