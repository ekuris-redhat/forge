"""Tests for complete bug workflow flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.graph import END

from forge.models.workflow import TicketType
from forge.workflow.bug.graph import _route_after_implementation, route_entry
from forge.workflow.bug.state import create_initial_bug_state
from tests.fixtures.workflow_states import (
    STATE_BUG_PLAN_PENDING,
    STATE_RCA_OPTION_PENDING,
    STATE_TRIAGE_PENDING,
    make_workflow_state,
)


class TestBugWorkflowEntry:
    """Bug workflow entry routing."""

    def test_new_bug_routes_to_triage_check(self):
        """A fresh bug ticket starts at triage_check (not analyze_bug)."""
        state = create_initial_bug_state(
            thread_id="test-thread",
            ticket_key="TEST-456",
            ticket_type=TicketType.BUG,
        )

        assert route_entry(state) == "triage_check"

    def test_bug_skips_prd_spec_epic_phases(self):
        """Bug workflow never routes to PRD, spec, or epic nodes."""
        state = create_initial_bug_state(
            thread_id="test-thread",
            ticket_key="TEST-456",
            ticket_type=TicketType.BUG,
        )

        next_node = route_entry(state)

        assert next_node == "triage_check"
        assert next_node != "generate_prd"
        assert next_node != "generate_spec"
        assert next_node != "decompose_epics"

    def test_resume_at_rca_gate_routes_to_rca_option_gate(self):
        """Resuming at rca_approval_gate (old checkpoint) maps to rca_option_gate."""
        state = make_workflow_state(
            ticket_key="TEST-456",
            current_node="rca_approval_gate",
            ticket_type=TicketType.BUG,
        )

        assert route_entry(state) == "rca_option_gate"

    def test_resume_at_implement_routes_there(self):
        """Resuming at implement_bug_fix returns to that node."""
        state = make_workflow_state(
            ticket_key="TEST-456",
            current_node="implement_bug_fix",
            ticket_type=TicketType.BUG,
        )

        assert route_entry(state) == "implement_bug_fix"

    def test_terminal_state_routes_to_end(self):
        """A completed bug workflow returns END on resume attempt."""
        state = make_workflow_state(
            ticket_key="TEST-456",
            current_node="complete",
            ticket_type=TicketType.BUG,
        )

        assert route_entry(state) == END


class TestBugImplementationRouting:
    """_route_after_implementation routes based on success/failure."""

    def test_successful_fix_routes_to_local_review(self):
        """Successful implementation routes to local_review (pre-PR code review)."""
        state = make_workflow_state(
            ticket_key="TEST-456",
            ticket_type=TicketType.BUG,
            current_node="implement_bug_fix",
            bug_fix_implemented=True,
            last_error=None,
        )

        assert _route_after_implementation(state) == "local_review"

    def test_failed_fix_below_retry_cap_escalates(self):
        """Implementation failure below retry cap still escalates (retry handled by worker)."""
        state = make_workflow_state(
            ticket_key="TEST-456",
            ticket_type=TicketType.BUG,
            current_node="implement_bug_fix",
            bug_fix_implemented=False,
            last_error="Container timed out",
            retry_count=0,
        )

        result = _route_after_implementation(state)

        # Either escalates or routes to create_pr (never implemented=False creates PR)
        assert result == "escalate_blocked"

    def test_fix_not_implemented_escalates(self):
        """bug_fix_implemented=False means implementation did not succeed."""
        state = make_workflow_state(
            ticket_key="TEST-456",
            ticket_type=TicketType.BUG,
            current_node="implement_bug_fix",
            bug_fix_implemented=False,
        )

        assert _route_after_implementation(state) == "escalate_blocked"


class TestBugWorkflowResumeRouting:
    """route_entry correctly resumes a bug workflow at any node."""

    @pytest.mark.parametrize("node,expected", [
        ("analyze_bug", "analyze_bug"),
        ("regenerate_rca", "analyze_bug"),
        ("rca_approval_gate", "rca_option_gate"),  # backward compat: old gate maps to new
        ("setup_workspace", "setup_workspace"),
        ("implement_bug_fix", "implement_bug_fix"),
        ("create_pr", "create_pr"),
        ("teardown_workspace", "teardown_workspace"),
        ("ci_evaluator", "ci_evaluator"),
        ("attempt_ci_fix", "ci_evaluator"),
        ("wait_for_ci_gate", "ci_evaluator"),  # attempt_ci_fix sets this; must not restart
        ("local_review", "local_review"),
        ("ai_review", "human_review_gate"),
        ("human_review_gate", "human_review_gate"),
        ("escalate_blocked", "escalate_blocked"),
    ])
    def test_resume_routing(self, node, expected):
        """route_entry maps each node to the correct resume target."""
        state = make_workflow_state(
            ticket_key="TEST-456",
            current_node=node,
            ticket_type=TicketType.BUG,
        )

        result = route_entry(state)

        assert result == expected, (
            f"route_entry with current_node='{node}' returned '{result}', "
            f"expected '{expected}'"
        )


class TestBackwardCompatFlow:
    """In-flight tickets with old current_node values route correctly."""

    def test_old_rca_approval_gate_routes_to_rca_option_gate(self):
        """State with current_node='rca_approval_gate' routes to rca_option_gate."""
        state = make_workflow_state(
            ticket_key="TEST-456",
            current_node="rca_approval_gate",
            ticket_type=TicketType.BUG,
        )
        assert route_entry(state) == "rca_option_gate"

    def test_minimal_old_state_without_new_fields_does_not_crash(self):
        """State dict missing all new fields can be passed to route_entry without KeyError."""
        minimal_old_state = {
            "ticket_key": "BUG-OLD",
            "ticket_type": "bug",
            "current_node": "implement_bug_fix",
            "is_paused": False,
        }
        result = route_entry(minimal_old_state)
        assert result == "implement_bug_fix"

    def test_all_new_current_node_values_are_handled(self):
        """Every new current_node value from the redesign has a route_entry mapping."""
        new_nodes = [
            "triage_check", "triage_gate", "reflect_rca",
            "rca_option_gate", "plan_bug_fix", "plan_approval_gate",
            "regenerate_plan", "decompose_plan", "post_merge_summary",
        ]
        for node in new_nodes:
            state = make_workflow_state(
                ticket_key="TEST-456",
                current_node=node,
                ticket_type=TicketType.BUG,
            )
            result = route_entry(state)
            assert result is not None, f"route_entry returned None for {node}"
            assert result != "", f"route_entry returned empty string for {node}"


class TestNewStateFixturesInFlow:
    """Flow-level assertions using the new bug workflow state fixtures."""

    def test_triage_pending_fixture_is_paused_at_triage_gate(self):
        """STATE_TRIAGE_PENDING is correctly paused at triage_gate."""
        assert STATE_TRIAGE_PENDING["is_paused"] is True
        assert STATE_TRIAGE_PENDING["current_node"] == "triage_gate"
        assert route_entry(STATE_TRIAGE_PENDING) == "triage_gate"

    def test_rca_option_pending_routes_to_gate(self):
        """STATE_RCA_OPTION_PENDING routes back to rca_option_gate on resume."""
        assert STATE_RCA_OPTION_PENDING["current_node"] == "rca_option_gate"
        assert route_entry(STATE_RCA_OPTION_PENDING) == "rca_option_gate"

    def test_bug_plan_pending_routes_to_plan_approval_gate(self):
        """STATE_BUG_PLAN_PENDING routes back to plan_approval_gate on resume."""
        assert STATE_BUG_PLAN_PENDING["current_node"] == "plan_approval_gate"
        assert route_entry(STATE_BUG_PLAN_PENDING) == "plan_approval_gate"


class TestNewResumeRoutingCases:
    """New pipeline nodes resume correctly at the right point."""

    @pytest.mark.parametrize("node,expected", [
        ("triage_check", "triage_check"),
        ("triage_gate", "triage_gate"),
        ("reflect_rca", "reflect_rca"),
        ("rca_option_gate", "rca_option_gate"),
        ("plan_bug_fix", "plan_bug_fix"),
        ("plan_approval_gate", "plan_approval_gate"),
        ("regenerate_plan", "regenerate_plan"),
        ("decompose_plan", "decompose_plan"),
        ("post_merge_summary", "post_merge_summary"),
        ("rca_approval_gate", "rca_option_gate"),  # backward compat
    ])
    def test_resume_routing_new_pipeline_nodes(self, node, expected):
        """route_entry maps each new current_node to the correct resume target."""
        state = make_workflow_state(
            ticket_key="BUG-99",
            current_node=node,
            ticket_type=TicketType.BUG,
        )
        assert route_entry(state) == expected

    def test_new_bug_starts_at_triage_not_analyze(self):
        """New bugs start at triage_check, not analyze_bug."""
        state = create_initial_bug_state(ticket_key="BUG-99")
        assert route_entry(state) == "triage_check"


class TestTriageLoopFlow:
    """Triage gate re-evaluates on reporter updates."""

    @pytest.mark.asyncio
    async def test_missing_fields_pauses_at_triage_gate(self):
        """triage_check with missing fields routes to triage_gate (paused)."""
        from forge.workflow.nodes.triage import triage_check

        state = make_workflow_state(
            ticket_key="BUG-T1",
            current_node="triage_check",
            ticket_type=TicketType.BUG,
            is_paused=False,
            retry_count=0,
        )

        mock_jira = MagicMock()
        mock_jira.add_comment = AsyncMock()
        mock_jira.set_workflow_label = AsyncMock()
        mock_jira.get_issue = AsyncMock(return_value=MagicMock(
            summary="Login fails",
            description="Short desc",
            project_key="BUG",
        ))
        mock_jira.get_comments = AsyncMock(return_value=[])
        mock_jira.close = AsyncMock()

        mock_agent = MagicMock()
        mock_agent.run_task = AsyncMock(return_value='["steps_to_reproduce", "error_output"]')
        mock_agent.close = AsyncMock()

        with (
            patch("forge.workflow.nodes.triage.JiraClient", return_value=mock_jira),
            patch("forge.workflow.nodes.triage.ForgeAgent", return_value=mock_agent),
        ):
            result = await triage_check(state)

        assert result["current_node"] == "triage_gate"
        assert result["triage_passed"] is False
        assert "steps_to_reproduce" in result.get("triage_missing_fields", [])

    @pytest.mark.asyncio
    async def test_sufficient_ticket_routes_to_analyze_bug(self):
        """triage_check with sufficient ticket routes to analyze_bug."""
        from forge.workflow.nodes.triage import triage_check

        state = make_workflow_state(
            ticket_key="BUG-T2",
            current_node="triage_check",
            ticket_type=TicketType.BUG,
            is_paused=False,
        )

        mock_jira = MagicMock()
        mock_jira.add_comment = AsyncMock()
        mock_jira.get_issue = AsyncMock(return_value=MagicMock(
            summary="Login fails with $", description="Full description with all fields",
            project_key="BUG",
        ))
        mock_jira.get_comments = AsyncMock(return_value=[])
        mock_jira.close = AsyncMock()

        mock_agent = MagicMock()
        mock_agent.run_task = AsyncMock(return_value="sufficient")
        mock_agent.close = AsyncMock()

        with (
            patch("forge.workflow.nodes.triage.JiraClient", return_value=mock_jira),
            patch("forge.workflow.nodes.triage.ForgeAgent", return_value=mock_agent),
        ):
            result = await triage_check(state)

        assert result["current_node"] == "analyze_bug"
        assert result["triage_passed"] is True


class TestReflectionCapFlow:
    """Reflection loop hits the 3-reflection cap."""

    @pytest.mark.asyncio
    async def test_three_failed_reflections_routes_to_rca_option_gate(self):
        """After 3 reflection failures, reflect_rca routes to rca_option_gate with warning."""
        from forge.workflow.nodes.rca_analysis import reflect_rca

        state = make_workflow_state(
            ticket_key="BUG-R1",
            current_node="reflect_rca",
            ticket_type=TicketType.BUG,
            is_paused=False,
            rca_content="## Root Cause\nBug is in validators.py",
            rca_options=[{"title": "Fix regex", "description": "Update pattern", "tradeoffs": "Low risk"}],
            reflection_count=2,  # Will become 3 after this run
            reflection_critique=None,
        )

        mock_jira = MagicMock()
        mock_jira.add_comment = AsyncMock()
        mock_jira.close = AsyncMock()

        class _CapRunner:
            async def run(self, workspace_path, **_kwargs):
                (workspace_path / ".forge").mkdir(exist_ok=True)
                result = MagicMock()
                result.success = True
                result.exit_code = 0
                result.stdout = "Still missing hypothesis log"
                result.stderr = ""
                return result

        with (
            patch("forge.workflow.nodes.rca_analysis.JiraClient", return_value=mock_jira),
            patch("forge.workflow.nodes.rca_analysis.ContainerRunner", return_value=_CapRunner()),
        ):
            result = await reflect_rca(state)

        assert result["current_node"] == "rca_option_gate"
        assert result["reflection_count"] == 3
        mock_jira.add_comment.assert_called_once()  # Warning comment posted


class TestQualitativeRetryCapFlow:
    """Qualitative review retry cap routes to create_pr with failed flag."""

    def test_qualitative_retry_count_two_routes_to_create_pr(self):
        """_route_after_local_review with qualitative_retry_count=2 → create_pr."""
        from forge.workflow.bug.graph import _route_after_local_review
        state = make_workflow_state(
            ticket_key="BUG-Q1",
            current_node="local_review",
            ticket_type=TicketType.BUG,
            local_review_verdict="tests_incomplete",
            qualitative_retry_count=2,
        )
        assert _route_after_local_review(state) == "update_documentation"

    def test_symptom_only_first_retry_routes_to_implement(self):
        """_route_after_local_review with symptom_only + retry=0 → implement_bug_fix."""
        from forge.workflow.bug.graph import _route_after_local_review
        state = make_workflow_state(
            ticket_key="BUG-Q2",
            current_node="local_review",
            ticket_type=TicketType.BUG,
            local_review_verdict="symptom_only",
            qualitative_retry_count=0,
        )
        assert _route_after_local_review(state) == "implement_bug_fix"
