"""Tests for forge:yolo auto-approval mode."""

import pytest

from forge.models.workflow import ForgeLabel, TicketType
from forge.workflow.feature.state import create_initial_feature_state
from forge.workflow.bug.state import create_initial_bug_state


class TestForgeLabelYolo:
    def test_yolo_label_value(self):
        assert ForgeLabel.YOLO == "forge:yolo"

    def test_yolo_label_is_string(self):
        assert isinstance(ForgeLabel.YOLO, str)


class TestYoloModeDefaultsToFalse:
    def test_feature_state_yolo_mode_defaults_false(self):
        state = create_initial_feature_state("TEST-1")
        assert state.get("yolo_mode") is False

    def test_bug_state_yolo_mode_defaults_false(self):
        state = create_initial_bug_state("BUG-1")
        assert state.get("yolo_mode") is False

    def test_feature_state_yolo_mode_can_be_set_true(self):
        state = create_initial_feature_state("TEST-1", yolo_mode=True)
        assert state["yolo_mode"] is True

    def test_bug_state_yolo_mode_can_be_set_true(self):
        state = create_initial_bug_state("BUG-1", yolo_mode=True)
        assert state["yolo_mode"] is True


class TestBuildInitialStateYoloMode:
    """Tests for yolo_mode initialization from Jira payload."""

    def _make_worker(self):
        from unittest.mock import MagicMock
        from forge.orchestrator.worker import OrchestratorWorker
        worker = OrchestratorWorker.__new__(OrchestratorWorker)
        worker.settings = MagicMock()
        worker.router = MagicMock()
        return worker

    def _make_message(self, labels: list):
        from unittest.mock import MagicMock
        from forge.models.events import EventSource
        msg = MagicMock()
        msg.ticket_key = "TEST-1"
        msg.source = EventSource.JIRA
        msg.event_type = "jira:issue_updated"
        msg.event_id = "evt-1"
        msg.retry_count = 0
        msg.payload = {
            "issue": {
                "fields": {
                    "issuetype": {"name": "Feature"},
                    "labels": labels,
                }
            }
        }
        return msg

    def test_yolo_mode_true_when_label_present(self):
        worker = self._make_worker()
        msg = self._make_message(["forge:managed", "forge:yolo"])
        state = worker._build_initial_state(msg)
        assert state["yolo_mode"] is True

    def test_yolo_mode_false_when_label_absent(self):
        worker = self._make_worker()
        msg = self._make_message(["forge:managed"])
        state = worker._build_initial_state(msg)
        assert state["yolo_mode"] is False

    def test_yolo_mode_false_when_no_labels(self):
        worker = self._make_worker()
        msg = self._make_message([])
        state = worker._build_initial_state(msg)
        assert state["yolo_mode"] is False

    def test_yolo_mode_false_for_github_source(self):
        from unittest.mock import MagicMock
        from forge.models.events import EventSource
        msg = MagicMock()
        msg.ticket_key = "TEST-1"
        msg.source = EventSource.GITHUB
        msg.event_type = "pull_request"
        msg.event_id = "evt-1"
        msg.retry_count = 0
        msg.payload = {"pull_request": {"number": 1}}
        worker = self._make_worker()
        state = worker._build_initial_state(msg)
        assert state["yolo_mode"] is False


class TestYoloLabelAddedMidWorkflow:
    """When forge:yolo is added while paused at a gate, yolo_mode is set and workflow unpauses."""

    def _make_yolo_label_message(self, current_labels: str, previous_labels: str = "") -> "QueueMessage":
        from forge.models.events import EventSource
        from forge.queue.models import QueueMessage
        return QueueMessage(
            message_id="1234567890-0",
            event_id="test-event-yolo",
            source=EventSource.JIRA,
            event_type="jira:issue_updated",
            ticket_key="TEST-1",
            payload={
                "changelog": {
                    "items": [
                        {
                            "field": "labels",
                            "fromString": previous_labels,
                            "toString": current_labels,
                        }
                    ]
                },
                "issue": {"fields": {"labels": current_labels.split()}},
            },
        )

    def _make_gate_state(self, current_node: str, **extra) -> dict:
        base = {
            "ticket_key": "TEST-1",
            "ticket_type": "Feature",
            "current_node": current_node,
            "is_paused": True,
            "yolo_mode": False,
            "revision_requested": False,
            "feedback_comment": None,
            "is_question": False,
            "context": {},
        }
        return {**base, **extra}

    @pytest.mark.asyncio
    async def test_yolo_label_addition_at_prd_gate_activates_yolo(self):
        from forge.orchestrator.worker import OrchestratorWorker
        worker = OrchestratorWorker(consumer_name="test-worker")
        message = self._make_yolo_label_message(
            current_labels="forge:managed forge:yolo",
            previous_labels="forge:managed",
        )
        state = self._make_gate_state("prd_approval_gate")
        result = await worker._handle_resume_event(message, state)
        assert result["yolo_mode"] is True
        assert result["is_paused"] is False

    @pytest.mark.asyncio
    async def test_yolo_label_addition_outside_gate_does_not_activate(self):
        from forge.orchestrator.worker import OrchestratorWorker
        worker = OrchestratorWorker(consumer_name="test-worker")
        message = self._make_yolo_label_message(
            current_labels="forge:managed forge:yolo",
            previous_labels="forge:managed",
        )
        state = self._make_gate_state("generate_spec")
        result = await worker._handle_resume_event(message, state)
        # Not at a gate — is_yolo flag should not fire; workflow must stay paused
        assert result.get("yolo_mode") is False
        assert result.get("is_paused") is True

    @pytest.mark.asyncio
    async def test_yolo_label_already_present_does_not_re_trigger(self):
        from forge.orchestrator.worker import OrchestratorWorker
        worker = OrchestratorWorker(consumer_name="test-worker")
        # forge:yolo was already in fromString — not a new addition
        message = self._make_yolo_label_message(
            current_labels="forge:yolo forge:prd-approved",
            previous_labels="forge:yolo forge:prd-pending",
        )
        state = self._make_gate_state("prd_approval_gate", yolo_mode=True)
        result = await worker._handle_resume_event(message, state)
        # forge:yolo was already present — is_yolo should not re-trigger
        # yolo_mode stays True (copied from state), is_paused is False (prd-approved fired)
        assert result["yolo_mode"] is True  # preserved from input state


class TestYoloGateRouting:
    """Each approval gate routing function auto-approves when yolo_mode=True."""

    def _feature_state(self, current_node: str, **extra) -> dict:
        from forge.workflow.feature.state import create_initial_feature_state
        state = create_initial_feature_state("TEST-1")
        state["current_node"] = current_node
        state["is_paused"] = True
        state["yolo_mode"] = True
        state.update(extra)
        return state

    def test_prd_route_auto_approves_in_yolo_mode(self):
        from forge.workflow.gates.prd_approval import route_prd_approval
        state = self._feature_state("prd_approval_gate", prd_content="# PRD")
        assert route_prd_approval(state) == "generate_spec"

    def test_spec_route_auto_approves_in_yolo_mode(self):
        from forge.workflow.gates.spec_approval import route_spec_approval
        state = self._feature_state("spec_approval_gate", spec_content="# Spec")
        assert route_spec_approval(state) == "decompose_epics"

    def test_plan_route_auto_approves_in_yolo_mode(self):
        from forge.workflow.gates.plan_approval import route_plan_approval
        state = self._feature_state("plan_approval_gate", epic_keys=["EPIC-1"])
        assert route_plan_approval(state) == "generate_tasks"

    def test_task_route_auto_approves_in_yolo_mode(self):
        from forge.workflow.gates.task_approval import route_task_approval
        state = self._feature_state("task_approval_gate", task_keys=["TASK-1"])
        assert route_task_approval(state) == "task_router"

    def test_yolo_false_still_pauses_at_prd_gate(self):
        from langgraph.graph import END
        from forge.workflow.gates.prd_approval import route_prd_approval
        from forge.workflow.feature.state import create_initial_feature_state
        state = create_initial_feature_state("TEST-1")
        state["current_node"] = "prd_approval_gate"
        state["is_paused"] = True
        state["yolo_mode"] = False
        state["prd_content"] = "# PRD"
        assert route_prd_approval(state) == END

    def test_yolo_does_not_override_question_routing(self):
        from forge.workflow.gates.prd_approval import route_prd_approval
        state = self._feature_state("prd_approval_gate", prd_content="# PRD")
        state["is_question"] = True
        state["feedback_comment"] = "?Why REST?"
        assert route_prd_approval(state) == "answer_question"
