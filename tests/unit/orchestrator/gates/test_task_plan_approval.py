"""Unit tests for the task takeover plan approval gate and routing logic."""

import pytest
from langgraph.graph import END

from forge.models.workflow import TicketType
from forge.workflow.gates.task_plan_approval import (
    route_task_plan_approval,
    task_plan_approval_gate,
)
from forge.workflow.task_takeover.state import create_initial_task_takeover_state


class TestTaskPlanApprovalGate:
    """Tests for task_plan_approval_gate node."""

    def test_gate_pauses_workflow(self) -> None:
        """Gate sets is_paused=True and updates current_node."""
        state = create_initial_task_takeover_state("TASK-100")
        state["current_node"] = "generate_plan"

        result = task_plan_approval_gate(state)

        assert result["is_paused"] is True
        assert result["current_node"] == "task_plan_approval_gate"


class TestRouteTaskPlanApproval:
    """Tests for route_task_plan_approval function."""

    @pytest.fixture
    def paused_state(self):
        """Standard paused state at task plan approval gate."""
        state = create_initial_task_takeover_state("TASK-100")
        state["current_node"] = "task_plan_approval_gate"
        state["is_paused"] = True
        return state

    def test_routes_to_end_when_still_paused(self, paused_state) -> None:
        """If still paused and no signals are present, route to END."""
        result = route_task_plan_approval(paused_state)
        assert result == END

    def test_routes_to_setup_workspace_on_approval(self, paused_state) -> None:
        """When resumed with approval, is_paused is False and routes to setup_workspace."""
        paused_state["is_paused"] = False

        result = route_task_plan_approval(paused_state)
        assert result == "setup_workspace"

    def test_routes_to_regenerate_plan_on_feedback_comment(self, paused_state) -> None:
        """Comment starting with '!' triggers feedback classification and routes to regenerate_plan."""
        # Scenario A: feedback is processed by worker and comes in as revision_requested
        state_worker = {
            **paused_state,
            "revision_requested": True,
            "feedback_comment": "Please rewrite the logging part.",
        }
        assert route_task_plan_approval(state_worker) == "regenerate_plan"

        # Scenario B: feedback comment with '!' is evaluated directly by the router (prefix integration check)
        state_direct = {
            **paused_state,
            "feedback_comment": "!Please rewrite the logging part.",
        }
        assert route_task_plan_approval(state_direct) == "regenerate_plan"

    def test_routes_to_answer_question_on_question_comment_with_prefix(self, paused_state) -> None:
        """Comment starting with '?' or '@forge ask' triggers QUESTION classification and routes to answer_question."""
        # Scenario A: is_question is set
        state_worker = {
            **paused_state,
            "is_question": True,
            "feedback_comment": "?Why use REST?",
        }
        assert route_task_plan_approval(state_worker) == "answer_question"

        # Scenario B: comment starting with '?' is evaluated directly by prefix classifier
        state_direct_question = {
            **paused_state,
            "feedback_comment": "?Why use REST?",
        }
        assert route_task_plan_approval(state_direct_question) == "answer_question"

        # Scenario C: comment starting with '@forge ask' is evaluated directly by prefix classifier
        state_direct_ask = {
            **paused_state,
            "feedback_comment": "@forge ask can you explain more?",
        }
        assert route_task_plan_approval(state_direct_ask) == "answer_question"

    def test_yolo_mode_auto_approves(self, paused_state) -> None:
        """YOLO mode routes directly to setup_workspace."""
        paused_state["yolo_mode"] = True
        result = route_task_plan_approval(paused_state)
        assert result == "setup_workspace"

    def test_informational_comment_ignored(self, paused_state) -> None:
        """Standard informational comments do not trigger transition and stay in paused state (routes to END)."""
        paused_state["feedback_comment"] = "This is a plain comment with no special prefix"
        # Standard comments don't change is_paused to False, or set revision_requested/is_question
        result = route_task_plan_approval(paused_state)
        assert result == END
