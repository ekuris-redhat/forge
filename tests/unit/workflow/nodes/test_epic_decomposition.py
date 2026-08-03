"""Unit tests for epic decomposition node — repo resolution paths."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.integrations.jira.client import MissingProjectConfig
from forge.models.workflow import ForgeLabel
from forge.workflow.nodes.epic_decomposition import decompose_epics, regenerate_all_epics


@pytest.fixture
def base_state():
    return {
        "ticket_key": "MYPROJ-1",
        "spec_content": "Build a backend service.",
        "qa_history": [],
        "generation_context": {},
        "retry_count": 0,
    }


@pytest.fixture
def mock_issue():
    issue = MagicMock()
    issue.project_key = "MYPROJ"
    issue.summary = "Test Feature"
    return issue


@pytest.fixture
def mock_epics_data():
    return [{"summary": "Epic One", "plan": "Do stuff.", "repo": "acme/backend"}]


class TestDecomposeEpicsRepoResolution:
    """Tests for how decompose_epics resolves available repos."""

    @pytest.mark.asyncio
    async def test_uses_project_repos_from_jira_property(
        self, base_state, mock_issue, mock_epics_data
    ):
        """decompose_epics passes forge.repos project property to the agent context."""
        with (
            patch("forge.workflow.nodes.epic_decomposition.JiraClient") as MockJira,
            patch("forge.workflow.nodes.epic_decomposition.ForgeAgent") as MockAgent,
            patch("forge.workflow.nodes.epic_decomposition.post_qa_summary_if_needed"),
        ):
            mock_jira = AsyncMock()
            MockJira.return_value = mock_jira
            mock_jira.get_issue = AsyncMock(return_value=mock_issue)
            mock_jira.get_labels = AsyncMock(return_value=[])
            mock_jira.get_project_repos = AsyncMock(return_value=["acme/backend", "acme/frontend"])
            mock_jira.create_epic = AsyncMock(return_value="MYPROJ-100")
            mock_jira.set_workflow_label = AsyncMock()
            mock_jira.add_comment = AsyncMock()

            mock_agent = AsyncMock()
            MockAgent.return_value = mock_agent
            captured_context: dict = {}

            async def capture_generate_epics(_spec, context):
                captured_context.update(context)
                return mock_epics_data

            mock_agent.generate_epics = capture_generate_epics

            await decompose_epics(base_state)

        assert "acme/backend" in captured_context["available_repos"]
        assert "acme/frontend" in captured_context["available_repos"]

    @pytest.mark.asyncio
    async def test_also_includes_label_repos_alongside_project_repos(
        self, base_state, mock_issue, mock_epics_data
    ):
        """Repos from Feature labels are merged with forge.repos project property."""
        with (
            patch("forge.workflow.nodes.epic_decomposition.JiraClient") as MockJira,
            patch("forge.workflow.nodes.epic_decomposition.ForgeAgent") as MockAgent,
            patch("forge.workflow.nodes.epic_decomposition.post_qa_summary_if_needed"),
        ):
            mock_jira = AsyncMock()
            MockJira.return_value = mock_jira
            mock_jira.get_issue = AsyncMock(return_value=mock_issue)
            mock_jira.get_labels = AsyncMock(return_value=["repo:acme/infra"])
            mock_jira.get_project_repos = AsyncMock(return_value=["acme/backend"])
            mock_jira.create_epic = AsyncMock(return_value="MYPROJ-100")
            mock_jira.set_workflow_label = AsyncMock()
            mock_jira.add_comment = AsyncMock()

            mock_agent = AsyncMock()
            MockAgent.return_value = mock_agent
            captured_context: dict = {}

            async def capture_generate_epics(_spec, context):
                captured_context.update(context)
                return mock_epics_data

            mock_agent.generate_epics = capture_generate_epics

            await decompose_epics(base_state)

        repos = set(captured_context["available_repos"])
        assert "acme/infra" in repos
        assert "acme/backend" in repos

    @pytest.mark.asyncio
    async def test_blocks_and_comments_when_forge_repos_missing(self, base_state, mock_issue):
        """Posts blocking comment and sets forge:blocked when forge.repos is not set."""
        mock_settings = MagicMock()
        mock_settings.forge_require_project_config = True
        mock_settings.known_repos = []
        with (
            patch("forge.workflow.nodes.epic_decomposition.JiraClient") as MockJira,
            patch("forge.workflow.nodes.epic_decomposition.ForgeAgent") as MockAgent,
            patch("forge.workflow.nodes.epic_decomposition.post_qa_summary_if_needed"),
            patch("forge.workflow.nodes.epic_decomposition.get_settings", return_value=mock_settings),
        ):
            mock_jira = AsyncMock()
            MockJira.return_value = mock_jira
            mock_jira.get_issue = AsyncMock(return_value=mock_issue)
            mock_jira.get_labels = AsyncMock(return_value=[])
            mock_jira.get_project_repos = AsyncMock(
                side_effect=MissingProjectConfig("forge.repos not set for project MYPROJ")
            )
            mock_jira.set_workflow_label = AsyncMock()
            mock_jira.add_comment = AsyncMock()

            MockAgent.return_value = AsyncMock()

            result = await decompose_epics(base_state)

        mock_jira.add_comment.assert_called()
        comment_text = mock_jira.add_comment.call_args[0][1]
        assert "forge.repos" in comment_text
        assert "forge:retry" in comment_text

        mock_jira.set_workflow_label.assert_called_once_with(
            "MYPROJ-1", ForgeLabel.BLOCKED
        )

        assert result["last_error"]
        assert result["current_node"] == "decompose_epics"

    @pytest.mark.asyncio
    async def test_blocks_and_comments_when_forge_repos_malformed(self, base_state, mock_issue):
        """Posts blocking comment and sets forge:blocked when forge.repos has invalid entries."""
        mock_settings = MagicMock()
        mock_settings.forge_require_project_config = True
        mock_settings.known_repos = []
        with (
            patch("forge.workflow.nodes.epic_decomposition.JiraClient") as MockJira,
            patch("forge.workflow.nodes.epic_decomposition.ForgeAgent") as MockAgent,
            patch("forge.workflow.nodes.epic_decomposition.post_qa_summary_if_needed"),
            patch("forge.workflow.nodes.epic_decomposition.get_settings", return_value=mock_settings),
        ):
            mock_jira = AsyncMock()
            MockJira.return_value = mock_jira
            mock_jira.get_issue = AsyncMock(return_value=mock_issue)
            mock_jira.get_labels = AsyncMock(return_value=[])
            mock_jira.get_project_repos = AsyncMock(
                side_effect=MissingProjectConfig(
                    "forge.repos for project MYPROJ is malformed: ['backend-only']"
                )
            )
            mock_jira.set_workflow_label = AsyncMock()
            mock_jira.add_comment = AsyncMock()

            MockAgent.return_value = AsyncMock()

            result = await decompose_epics(base_state)

        mock_jira.set_workflow_label.assert_called_once_with(
            "MYPROJ-1", ForgeLabel.BLOCKED
        )
        assert result["last_error"]


class TestEpicRevisionState:
    """Tests for plan revision state cleanup."""

    @pytest.mark.asyncio
    async def test_decompose_epics_clears_revision_flags_on_success(
        self, base_state, mock_issue, mock_epics_data
    ):
        """Successful decomposition must not leave a pending revision at the plan gate."""
        state = {
            **base_state,
            "feedback_comment": "Split the authentication epic.",
            "revision_requested": True,
            "current_epic_key": "MYPROJ-99",
        }

        with (
            patch("forge.workflow.nodes.epic_decomposition.JiraClient") as MockJira,
            patch("forge.workflow.nodes.epic_decomposition.ForgeAgent") as MockAgent,
            patch("forge.workflow.nodes.epic_decomposition.post_qa_summary_if_needed"),
        ):
            mock_jira = AsyncMock()
            MockJira.return_value = mock_jira
            mock_jira.get_issue = AsyncMock(return_value=mock_issue)
            mock_jira.get_labels = AsyncMock(return_value=[])
            mock_jira.get_project_repos = AsyncMock(return_value=["acme/backend"])
            mock_jira.create_epic = AsyncMock(return_value="MYPROJ-100")
            mock_jira.set_workflow_label = AsyncMock()
            mock_jira.add_comment = AsyncMock()

            mock_agent = AsyncMock()
            MockAgent.return_value = mock_agent
            mock_agent.generate_epics = AsyncMock(return_value=mock_epics_data)

            result = await decompose_epics(state)

        assert result["current_node"] == "plan_approval_gate"
        assert result["revision_requested"] is False
        assert result["feedback_comment"] is None
        assert result["current_epic_key"] is None

    @pytest.mark.asyncio
    async def test_regenerate_all_epics_clears_revision_flags_after_new_epics(
        self, base_state, mock_issue, mock_epics_data
    ):
        """Full plan regeneration should return to the gate without looping."""
        state = {
            **base_state,
            "epic_keys": ["MYPROJ-10", "MYPROJ-11"],
            "feedback_comment": "Use smaller epics.",
            "revision_requested": True,
        }

        with (
            patch("forge.workflow.nodes.epic_decomposition.JiraClient") as MockJira,
            patch("forge.workflow.nodes.epic_decomposition.ForgeAgent") as MockAgent,
            patch("forge.workflow.nodes.epic_decomposition.post_qa_summary_if_needed"),
        ):
            mock_jira = AsyncMock()
            MockJira.return_value = mock_jira
            mock_jira.archive_issue = AsyncMock()
            mock_jira.get_issue = AsyncMock(return_value=mock_issue)
            mock_jira.get_labels = AsyncMock(return_value=[])
            mock_jira.get_project_repos = AsyncMock(return_value=["acme/backend"])
            mock_jira.create_epic = AsyncMock(return_value="MYPROJ-100")
            mock_jira.set_workflow_label = AsyncMock()
            mock_jira.add_comment = AsyncMock()

            mock_agent = AsyncMock()
            MockAgent.return_value = mock_agent
            import json
            delta_response = {
                "to_create": [{"summary": "Epic One", "description": "Do stuff.", "repo": "acme/backend"}],
                "to_edit": [],
                "to_archive": [{"key": "MYPROJ-10"}, {"key": "MYPROJ-11"}]
            }
            mock_agent.run_task = AsyncMock(return_value=json.dumps(delta_response))

            result = await regenerate_all_epics(state)

        assert mock_jira.archive_issue.call_count == 2
        mock_jira.archive_issue.assert_any_call("MYPROJ-10", archive_subtasks=True)
        mock_jira.archive_issue.assert_any_call("MYPROJ-11", archive_subtasks=True)
        assert result["epic_keys"] == ["MYPROJ-100"]
        assert result["current_node"] == "plan_approval_gate"
        assert result["revision_requested"] is False
        assert result["feedback_comment"] is None

    @pytest.mark.asyncio
    async def test_regenerate_all_epics_direct_single_ticket_update_bypass(
        self, base_state, mock_issue
    ):
        """If feedback requests a direct single-ticket update starting with !, bypass delta and delegate."""
        state = {
            **base_state,
            "epic_keys": ["MYPROJ-10", "MYPROJ-11"],
            "feedback_comment": "!MYPROJ-10 Add more logging instructions",
            "revision_requested": True,
        }

        with (
            patch("forge.workflow.nodes.epic_decomposition.JiraClient") as MockJira,
            patch("forge.workflow.nodes.epic_decomposition.ForgeAgent") as MockAgent,
            patch("forge.workflow.nodes.epic_decomposition.update_single_epic") as MockUpdateSingle,
        ):
            mock_jira = AsyncMock()
            MockJira.return_value = mock_jira
            mock_agent = AsyncMock()
            MockAgent.return_value = mock_agent

            MockUpdateSingle.return_value = {
                **state,
                "current_epic_key": None,
                "feedback_comment": None,
                "revision_requested": False,
                "current_node": "plan_approval_gate",
            }

            result = await regenerate_all_epics(state)

        # Verify update_single_epic was called, and delta orchestration was bypassed
        MockUpdateSingle.assert_called_once()
        called_state = MockUpdateSingle.call_args[0][0]
        assert called_state["current_epic_key"] == "MYPROJ-10"
        assert called_state["feedback_comment"] == "Add more logging instructions"

    @pytest.mark.asyncio
    async def test_regenerate_all_epics_calls_state_retrieval_and_delta_generation(
        self, base_state, mock_issue
    ):
        """regenerate_all_epics should fetch active state and generate LLM delta."""
        state = {
            **base_state,
            "epic_keys": ["MYPROJ-10"],
            "feedback_comment": "Add something.",
            "revision_requested": True,
        }

        with (
            patch("forge.workflow.nodes.epic_decomposition.JiraClient") as MockJira,
            patch("forge.workflow.nodes.epic_decomposition.ForgeAgent") as MockAgent,
            patch("forge.workflow.nodes.epic_decomposition.get_current_revision_state") as MockGetState,
            patch("forge.workflow.nodes.epic_decomposition.generate_revision_delta") as MockGenDelta,
            patch("forge.workflow.nodes.epic_decomposition.validate_delta_response") as MockValidate,
        ):
            mock_jira = AsyncMock()
            MockJira.return_value = mock_jira
            mock_jira.get_issue = AsyncMock(return_value=mock_issue)
            mock_jira.add_comment = AsyncMock()
            mock_jira.create_epic = AsyncMock(return_value="MYPROJ-100")

            mock_agent = AsyncMock()
            MockAgent.return_value = mock_agent

            MockGetState.return_value = [{"key": "MYPROJ-10", "summary": "Epic 10", "description": "Desc"}]
            MockGenDelta.return_value = {
                "to_create": [{"summary": "Epic 100", "description": "Desc 100"}],
                "to_edit": [],
                "to_archive": []
            }
            MockValidate.return_value = {
                "to_create": [{"summary": "Epic 100", "description": "Desc 100"}],
                "to_edit": [],
                "to_archive": []
            }

            await regenerate_all_epics(state)

        # Verify active state retrieval and delta generation calls were made
        MockGetState.assert_any_call(state, "epic", mock_jira)
        MockGenDelta.assert_called_once_with(state, [{"key": "MYPROJ-10", "summary": "Epic 10", "description": "Desc"}], "Add something.", mock_agent)

    @pytest.mark.asyncio
    async def test_regenerate_all_epics_corrective_retry_flow(
        self, base_state, mock_issue
    ):
        """On validation or key mismatch, perform exactly one corrective retry containing precise error."""
        state = {
            **base_state,
            "epic_keys": ["MYPROJ-10"],
            "feedback_comment": "Add database migration.",
            "revision_requested": True,
        }

        with (
            patch("forge.workflow.nodes.epic_decomposition.JiraClient") as MockJira,
            patch("forge.workflow.nodes.epic_decomposition.ForgeAgent") as MockAgent,
            patch("forge.workflow.nodes.epic_decomposition.get_current_revision_state") as MockGetState,
            patch("forge.workflow.nodes.epic_decomposition.generate_revision_delta") as MockGenDelta,
            patch("forge.workflow.nodes.epic_decomposition.post_status_comment") as MockPostStatus,
        ):
            mock_jira = AsyncMock()
            MockJira.return_value = mock_jira
            mock_jira.get_issue = AsyncMock(return_value=mock_issue)
            mock_jira.get_labels = AsyncMock(return_value=[])
            mock_jira.get_project_repos = AsyncMock(return_value=["acme/backend"])
            mock_jira.create_epic = AsyncMock(return_value="MYPROJ-100")
            mock_jira.set_workflow_label = AsyncMock()
            mock_jira.add_comment = AsyncMock()

            mock_agent = AsyncMock()
            MockAgent.return_value = mock_agent

            MockGetState.return_value = [{"key": "MYPROJ-10", "summary": "Epic 10", "description": "Desc"}]

            # 1st call: Key mismatch (INVALID-KEY is not in existing_epics)
            # 2nd call: Valid response
            MockGenDelta.side_effect = [
                {
                    "to_create": [],
                    "to_edit": [{"key": "INVALID-KEY", "summary": "Bad Epic", "description": "Bad Description"}],
                    "to_archive": []
                },
                {
                    "to_create": [{"summary": "Epic 100", "description": "Desc 100", "repo": "acme/backend"}],
                    "to_edit": [],
                    "to_archive": []
                }
            ]

            result = await regenerate_all_epics(state)

        # Assert we had exactly two generate_revision_delta calls (1 initial + 1 corrective retry)
        assert MockGenDelta.call_count == 2
        
        # Verify the corrective retry prompt contains the precise error message
        corrective_feedback_prompt = MockGenDelta.call_args_list[1][0][2]
        assert "Key 'INVALID-KEY' in to_edit is not an active ticket key" in corrective_feedback_prompt
        assert "Add database migration" in corrective_feedback_prompt

        # Verify a status comment was posted to Jira for the retry
        MockPostStatus.assert_any_call(
            mock_jira,
            "MYPROJ-1",
            "⚠️ Forge detected a validation error in the generated plan: Validation error: Key 'INVALID-KEY' in to_edit is not an active ticket key.. Retrying with corrective feedback..."
        )

        # Verify that after the retry, execution succeeded
        assert result["epic_keys"] == ["MYPROJ-10", "MYPROJ-100"]
        assert result["current_node"] == "plan_approval_gate"


    @pytest.mark.asyncio
    async def test_regenerate_all_epics_execution_halting_on_consecutive_failures(
        self, base_state, mock_issue
    ):
        """On second consecutive validation failure, cleanly halt execution, posting status comment."""
        state = {
            **base_state,
            "epic_keys": ["MYPROJ-10"],
            "feedback_comment": "Add database migration.",
            "revision_requested": True,
        }

        with (
            patch("forge.workflow.nodes.epic_decomposition.JiraClient") as MockJira,
            patch("forge.workflow.nodes.epic_decomposition.ForgeAgent") as MockAgent,
            patch("forge.workflow.nodes.epic_decomposition.get_current_revision_state") as MockGetState,
            patch("forge.workflow.nodes.epic_decomposition.generate_revision_delta") as MockGenDelta,
            patch("forge.workflow.nodes.epic_decomposition.post_status_comment") as MockPostStatus,
        ):
            mock_jira = AsyncMock()
            MockJira.return_value = mock_jira
            mock_jira.get_issue = AsyncMock(return_value=mock_issue)
            mock_jira.get_labels = AsyncMock(return_value=[])
            mock_jira.get_project_repos = AsyncMock(return_value=["acme/backend"])
            mock_jira.set_workflow_label = AsyncMock()
            mock_jira.add_comment = AsyncMock()

            mock_agent = AsyncMock()
            MockAgent.return_value = mock_agent

            MockGetState.return_value = [{"key": "MYPROJ-10", "summary": "Epic 10", "description": "Desc"}]

            # Always return key mismatch to trigger 2 failures
            MockGenDelta.return_value = {
                "to_create": [],
                "to_edit": [{"key": "INVALID-KEY", "summary": "Bad Epic", "description": "Bad Description"}],
                "to_archive": []
            }

            result = await regenerate_all_epics(state)

        # Assert we had exactly two generate_revision_delta calls (1 initial + 1 corrective retry)
        assert MockGenDelta.call_count == 2

        # Verify status comments posted
        # 1. Posted first error retry comment
        MockPostStatus.assert_any_call(
            mock_jira,
            "MYPROJ-1",
            "⚠️ Forge detected a validation error in the generated plan: Validation error: Key 'INVALID-KEY' in to_edit is not an active ticket key.. Retrying with corrective feedback..."
        )
        # 2. Posted halting comment
        MockPostStatus.assert_any_call(
            mock_jira,
            "MYPROJ-1",
            "⚠️ Forge has halted execution because it received an invalid plan from the AI generator twice consecutively.\n\n"
            "Manual intervention is required to review or refine the requirements."
        )

        # State should be left entirely untouched, returning original state
        assert result == state

        # Verify no epic creation or updates were made on the jira client
        mock_jira.create_epic.assert_not_called()
        mock_jira.update_summary_and_description.assert_not_called()
        mock_jira.archive_issue.assert_not_called()
