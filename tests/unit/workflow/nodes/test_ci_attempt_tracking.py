"""Unit tests for CI attempt tracking (AISOS-654)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.workflow.feature.state import FeatureState
from forge.workflow.nodes.ci_evaluator import evaluate_ci_status

# ── Helpers ───────────────────────────────────────────────────────────────────


def create_mock_github_client():
    """Create a mock GitHub client with common methods."""
    client = MagicMock()
    client.get_pull_request = AsyncMock()
    client.get_check_runs = AsyncMock()
    client.close = AsyncMock()
    return client


def create_base_state(**kwargs) -> FeatureState:
    """Create a base workflow state with CI fields."""
    defaults = {
        "ticket_key": "TEST-123",
        "pr_urls": ["https://github.com/org/repo/pull/42"],
        "ci_fix_attempt": 0,
        "ci_fix_max_attempts": 3,
        "ci_status": None,
        "ci_failed_checks": [],
        "ci_skipped_checks": [],
        "current_repo": "org/repo",
    }
    defaults.update(kwargs)
    return FeatureState(**defaults)


# ── State Initialization Tests ────────────────────────────────────────────────


class TestCIAttemptTrackingStateFields:
    """Test that current_attempt and max_attempts fields exist in state."""

    def test_current_attempt_in_ci_integration_state(self):
        """current_attempt must be a field in CIIntegrationState."""
        from forge.workflow.base import CIIntegrationState

        assert "ci_fix_attempt" in CIIntegrationState.__annotations__

    def test_max_attempts_in_ci_integration_state(self):
        """max_attempts must be a field in CIIntegrationState."""
        from forge.workflow.base import CIIntegrationState

        assert "ci_fix_max_attempts" in CIIntegrationState.__annotations__

    def test_feature_state_initializes_current_attempt_to_zero(self):
        """Feature state should initialize current_attempt to 0."""
        from forge.workflow.feature.state import create_initial_feature_state

        state = create_initial_feature_state(ticket_key="TEST-1")
        assert state.get("ci_fix_attempt") == 0

    def test_feature_state_initializes_max_attempts_from_config(self):
        """Feature state should initialize max_attempts from config."""
        from forge.workflow.feature.state import create_initial_feature_state

        state = create_initial_feature_state(ticket_key="TEST-1")
        # Default config value is 5
        assert state.get("ci_fix_max_attempts") is not None
        assert isinstance(state.get("ci_fix_max_attempts"), int)

    def test_bug_state_initializes_current_attempt_to_zero(self):
        """Bug state should initialize current_attempt to 0."""
        from forge.workflow.bug.state import create_initial_bug_state

        state = create_initial_bug_state(ticket_key="TEST-2")
        assert state.get("ci_fix_attempt") == 0

    def test_bug_state_initializes_max_attempts_from_config(self):
        """Bug state should initialize max_attempts from config."""
        from forge.workflow.bug.state import create_initial_bug_state

        state = create_initial_bug_state(ticket_key="TEST-2")
        # Default config value is 5
        assert state.get("ci_fix_max_attempts") is not None
        assert isinstance(state.get("ci_fix_max_attempts"), int)


# ── Attempt Increment Tests ───────────────────────────────────────────────────


class TestCIAttemptIncrement:
    """Test that current_attempt increments before each fix attempt."""

    @pytest.mark.asyncio
    async def test_first_ci_failure_increments_attempt_to_one(self):
        """First CI failure should increment current_attempt from 0 to 1."""
        state = create_base_state(ci_fix_attempt=0, ci_fix_max_attempts=3)

        github = create_mock_github_client()
        github.get_pull_request.return_value = {"head": {"sha": "abc123"}}
        github.get_check_runs.return_value = [
            {
                "name": "test",
                "status": "completed",
                "conclusion": "failure",
                "output": {},
                "html_url": "https://github.com/org/repo/runs/1",
            }
        ]

        with patch("forge.workflow.nodes.ci_evaluator.GitHubClient", return_value=github):
            with patch("forge.workflow.nodes.ci_evaluator.get_settings") as mock_settings:
                mock_settings.return_value.ci_fix_max_retries = 5
                mock_settings.return_value.ignored_ci_checks = ["tide"]
                result = await evaluate_ci_status(state)

        assert result["ci_fix_attempt"] == 1
        assert result["current_node"] == "attempt_ci_fix"

    @pytest.mark.asyncio
    async def test_second_ci_failure_increments_attempt_to_two(self):
        """Second CI failure should increment current_attempt from 1 to 2."""
        state = create_base_state(ci_fix_attempt=1, ci_fix_max_attempts=3)

        github = create_mock_github_client()
        github.get_pull_request.return_value = {"head": {"sha": "abc123"}}
        github.get_check_runs.return_value = [
            {
                "name": "test",
                "status": "completed",
                "conclusion": "failure",
                "output": {},
                "html_url": "https://github.com/org/repo/runs/1",
            }
        ]

        with patch("forge.workflow.nodes.ci_evaluator.GitHubClient", return_value=github):
            with patch("forge.workflow.nodes.ci_evaluator.get_settings") as mock_settings:
                mock_settings.return_value.ci_fix_max_retries = 5
                mock_settings.return_value.ignored_ci_checks = ["tide"]
                result = await evaluate_ci_status(state)

        assert result["ci_fix_attempt"] == 2
        assert result["current_node"] == "attempt_ci_fix"

    @pytest.mark.asyncio
    async def test_third_ci_failure_increments_attempt_to_three(self):
        """Third CI failure should increment current_attempt from 2 to 3."""
        state = create_base_state(ci_fix_attempt=2, ci_fix_max_attempts=3)

        github = create_mock_github_client()
        github.get_pull_request.return_value = {"head": {"sha": "abc123"}}
        github.get_check_runs.return_value = [
            {
                "name": "test",
                "status": "completed",
                "conclusion": "failure",
                "output": {},
                "html_url": "https://github.com/org/repo/runs/1",
            }
        ]

        with patch("forge.workflow.nodes.ci_evaluator.GitHubClient", return_value=github):
            with patch("forge.workflow.nodes.ci_evaluator.get_settings") as mock_settings:
                mock_settings.return_value.ci_fix_max_retries = 5
                mock_settings.return_value.ignored_ci_checks = ["tide"]
                result = await evaluate_ci_status(state)

        assert result["ci_fix_attempt"] == 3
        assert result["current_node"] == "attempt_ci_fix"


# ── Attempt Limit Validation Tests ────────────────────────────────────────────


class TestCIAttemptLimitValidation:
    """Test that current_attempt is validated against max_attempts."""

    @pytest.mark.asyncio
    async def test_attempt_at_max_limit_blocks_further_attempts(self):
        """When current_attempt equals max_attempts, no more attempts should be made."""
        state = create_base_state(ci_fix_attempt=3, ci_fix_max_attempts=3)

        github = create_mock_github_client()
        github.get_pull_request.return_value = {"head": {"sha": "abc123"}}
        github.get_check_runs.return_value = [
            {
                "name": "test",
                "status": "completed",
                "conclusion": "failure",
                "output": {},
                "html_url": "https://github.com/org/repo/runs/1",
            }
        ]

        with patch("forge.workflow.nodes.ci_evaluator.GitHubClient", return_value=github):
            with patch("forge.workflow.nodes.ci_evaluator.get_settings") as mock_settings:
                mock_settings.return_value.ci_fix_max_retries = 5
                mock_settings.return_value.ignored_ci_checks = ["tide"]
                with patch(
                    "forge.workflow.nodes.ci_evaluator.record_ci_fix_attempt"
                ) as mock_record:
                    result = await evaluate_ci_status(state)

        # Should not increment or route to attempt_ci_fix
        assert result["ci_fix_attempt"] == 3  # Unchanged
        assert result["current_node"] == "ci_evaluator"
        assert result["ci_status"] == "failed"
        assert "limit reached" in result["last_error"]

    @pytest.mark.asyncio
    async def test_attempt_exceeding_max_limit_blocks_further_attempts(self):
        """When current_attempt exceeds max_attempts, no more attempts should be made."""
        state = create_base_state(ci_fix_attempt=4, ci_fix_max_attempts=3)

        github = create_mock_github_client()
        github.get_pull_request.return_value = {"head": {"sha": "abc123"}}
        github.get_check_runs.return_value = [
            {
                "name": "test",
                "status": "completed",
                "conclusion": "failure",
                "output": {},
                "html_url": "https://github.com/org/repo/runs/1",
            }
        ]

        with patch("forge.workflow.nodes.ci_evaluator.GitHubClient", return_value=github):
            with patch("forge.workflow.nodes.ci_evaluator.get_settings") as mock_settings:
                mock_settings.return_value.ci_fix_max_retries = 5
                mock_settings.return_value.ignored_ci_checks = ["tide"]
                with patch(
                    "forge.workflow.nodes.ci_evaluator.record_ci_fix_attempt"
                ) as mock_record:
                    result = await evaluate_ci_status(state)

        # Should not increment or route to attempt_ci_fix
        assert result["ci_fix_attempt"] == 4  # Unchanged
        assert result["current_node"] == "ci_evaluator"
        assert result["ci_status"] == "failed"
        assert "limit reached" in result["last_error"]

    @pytest.mark.asyncio
    async def test_attempt_one_below_max_allows_final_attempt(self):
        """When current_attempt is one below max, one more attempt should be allowed."""
        state = create_base_state(ci_fix_attempt=2, ci_fix_max_attempts=3)

        github = create_mock_github_client()
        github.get_pull_request.return_value = {"head": {"sha": "abc123"}}
        github.get_check_runs.return_value = [
            {
                "name": "test",
                "status": "completed",
                "conclusion": "failure",
                "output": {},
                "html_url": "https://github.com/org/repo/runs/1",
            }
        ]

        with patch("forge.workflow.nodes.ci_evaluator.GitHubClient", return_value=github):
            with patch("forge.workflow.nodes.ci_evaluator.get_settings") as mock_settings:
                mock_settings.return_value.ci_fix_max_retries = 5
                mock_settings.return_value.ignored_ci_checks = ["tide"]
                result = await evaluate_ci_status(state)

        # Should increment and route to attempt_ci_fix
        assert result["ci_fix_attempt"] == 3
        assert result["current_node"] == "attempt_ci_fix"
        assert result["ci_status"] == "fixing"


# ── Attempt Reset Tests ───────────────────────────────────────────────────────


class TestCIAttemptReset:
    """Test that current_attempt resets when workflow completes or succeeds."""

    @pytest.mark.asyncio
    async def test_current_attempt_resets_on_ci_success(self):
        """When CI passes, current_attempt should reset to 0."""
        state = create_base_state(ci_fix_attempt=2, ci_fix_max_attempts=3)

        github = create_mock_github_client()
        github.get_pull_request.return_value = {"head": {"sha": "abc123"}}
        github.get_check_runs.return_value = [
            {
                "name": "test",
                "status": "completed",
                "conclusion": "success",
                "output": {},
                "html_url": "https://github.com/org/repo/runs/1",
            }
        ]

        with patch("forge.workflow.nodes.ci_evaluator.GitHubClient", return_value=github):
            with patch("forge.workflow.nodes.ci_evaluator.get_settings") as mock_settings:
                mock_settings.return_value.ignored_ci_checks = ["tide"]
                result = await evaluate_ci_status(state)

        assert result["ci_fix_attempt"] == 0
        assert result["current_node"] == "human_review_gate"
        assert result["ci_status"] == "passed"

    @pytest.mark.asyncio
    async def test_current_attempt_resets_on_workflow_completion(self):
        """When workflow completes (tasks complete), current_attempt should reset to 0."""
        from forge.workflow.nodes.human_review import complete_tasks

        state = create_base_state(
            ci_fix_attempt=2,
            implemented_tasks=["TASK-1", "TASK-2"],
        )

        with patch("forge.workflow.nodes.human_review.JiraClient") as mock_jira_class:
            mock_jira = MagicMock()
            mock_jira.transition_issue = AsyncMock()
            mock_jira.set_workflow_label = AsyncMock()
            mock_jira.close = AsyncMock()
            mock_jira_class.return_value = mock_jira

            result = await complete_tasks(state)

        assert result["ci_fix_attempt"] == 0
        assert result["tasks_completed"] is True


# ── Edge Case Tests ───────────────────────────────────────────────────────────


class TestCIAttemptEdgeCases:
    """Test edge cases for CI attempt tracking."""

    @pytest.mark.asyncio
    async def test_missing_current_attempt_defaults_to_zero(self):
        """If current_attempt is missing from state, it should default to 0."""
        state = create_base_state()
        # Remove current_attempt from state
        del state["ci_fix_attempt"]

        github = create_mock_github_client()
        github.get_pull_request.return_value = {"head": {"sha": "abc123"}}
        github.get_check_runs.return_value = [
            {
                "name": "test",
                "status": "completed",
                "conclusion": "failure",
                "output": {},
                "html_url": "https://github.com/org/repo/runs/1",
            }
        ]

        with patch("forge.workflow.nodes.ci_evaluator.GitHubClient", return_value=github):
            with patch("forge.workflow.nodes.ci_evaluator.get_settings") as mock_settings:
                mock_settings.return_value.ci_fix_max_retries = 5
                mock_settings.return_value.ignored_ci_checks = ["tide"]
                result = await evaluate_ci_status(state)

        # Should default to 0 and increment to 1
        assert result["ci_fix_attempt"] == 1

    @pytest.mark.asyncio
    async def test_missing_max_attempts_defaults_to_config_value(self):
        """If max_attempts is missing from state, it should default to 5."""
        state = create_base_state(ci_fix_attempt=0)
        # Remove max_attempts from state
        del state["ci_fix_max_attempts"]

        github = create_mock_github_client()
        github.get_pull_request.return_value = {"head": {"sha": "abc123"}}
        github.get_check_runs.return_value = [
            {
                "name": "test",
                "status": "completed",
                "conclusion": "failure",
                "output": {},
                "html_url": "https://github.com/org/repo/runs/1",
            }
        ]

        with patch("forge.workflow.nodes.ci_evaluator.GitHubClient", return_value=github):
            with patch("forge.workflow.nodes.ci_evaluator.get_settings") as mock_settings:
                mock_settings.return_value.ci_fix_max_retries = 5
                mock_settings.return_value.ignored_ci_checks = ["tide"]
                result = await evaluate_ci_status(state)

        # Should allow attempt since default is 5
        assert result["ci_fix_attempt"] == 1
        assert result["current_node"] == "attempt_ci_fix"

    @pytest.mark.asyncio
    async def test_max_attempts_one_allows_single_attempt(self):
        """When max_attempts is 1, only one attempt should be allowed."""
        state = create_base_state(ci_fix_attempt=0, ci_fix_max_attempts=1)

        github = create_mock_github_client()
        github.get_pull_request.return_value = {"head": {"sha": "abc123"}}
        github.get_check_runs.return_value = [
            {
                "name": "test",
                "status": "completed",
                "conclusion": "failure",
                "output": {},
                "html_url": "https://github.com/org/repo/runs/1",
            }
        ]

        with patch("forge.workflow.nodes.ci_evaluator.GitHubClient", return_value=github):
            with patch("forge.workflow.nodes.ci_evaluator.get_settings") as mock_settings:
                mock_settings.return_value.ci_fix_max_retries = 5
                mock_settings.return_value.ignored_ci_checks = ["tide"]
                result = await evaluate_ci_status(state)

        # Should allow first attempt
        assert result["ci_fix_attempt"] == 1
        assert result["current_node"] == "attempt_ci_fix"

        # Second failure should block
        state2 = create_base_state(ci_fix_attempt=1, ci_fix_max_attempts=1)
        with patch("forge.workflow.nodes.ci_evaluator.GitHubClient", return_value=github):
            with patch("forge.workflow.nodes.ci_evaluator.get_settings") as mock_settings:
                mock_settings.return_value.ci_fix_max_retries = 5
                mock_settings.return_value.ignored_ci_checks = ["tide"]
                with patch("forge.workflow.nodes.ci_evaluator.record_ci_fix_attempt"):
                    result2 = await evaluate_ci_status(state2)

        assert result2["ci_fix_attempt"] == 1  # Unchanged
        assert result2["current_node"] == "ci_evaluator"
        assert result2["ci_status"] == "failed"


class TestCIAttemptTokens:
    """Test token recording during CI fix attempts."""

    @pytest.mark.asyncio
    @patch("forge.workflow.nodes.ci_evaluator.JiraClient")
    @patch("forge.workflow.nodes.ci_evaluator.prepare_workspace")
    @patch("forge.workflow.nodes.ci_evaluator._fetch_ci_logs_and_artifacts")
    @patch("forge.workflow.nodes.ci_evaluator._collect_error_info")
    @patch("forge.workflow.nodes.ci_evaluator.load_prompt")
    @patch("forge.workflow.nodes.ci_evaluator.ContainerRunner")
    @patch("forge.workflow.nodes.ci_evaluator.GitOperations")
    @patch("forge.workflow.nodes.ci_evaluator.Workspace")
    async def test_attempt_ci_fix_records_tokens(
        self,
        _mock_workspace_class,
        mock_git_ops_class,
        mock_runner_class,
        mock_load_prompt,
        mock_collect_error_info,
        _mock_fetch_logs,
        mock_prepare_workspace,
        mock_jira_class,
        tmp_path,
    ):
        """Test that attempt_ci_fix correctly records input/output tokens in state."""
        from forge.workflow.nodes.ci_evaluator import attempt_ci_fix
        from forge.workflow.stats import STAGE_CI

        # 1. Setup mock state
        state = create_base_state(
            ci_fix_attempt=1, ci_failed_checks=[{"name": "pytest", "conclusion": "failure"}]
        )

        # 2. Setup mocks
        mock_jira = MagicMock()
        mock_jira.close = AsyncMock()
        mock_jira_class.return_value = mock_jira

        mock_prepare_workspace.return_value = (str(tmp_path), "main")
        mock_collect_error_info.return_value = "Some error details"
        mock_load_prompt.return_value = "Mocked Prompt"

        # We need fix plan file to exist so we don't skip the second phase
        fix_plan_file = tmp_path / ".forge" / "fix-plan.md"
        fix_plan_file.parent.mkdir(parents=True, exist_ok=True)
        fix_plan_file.write_text("Change line X to Y")

        # Mock ContainerRunner and its run method
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner

        # Phase 1: analysis, Phase 2: fix
        # Return mock results with defined token counts
        mock_result_1 = MagicMock()
        mock_result_1.input_tokens = 120
        mock_result_1.output_tokens = 45
        mock_result_1.stdout = "phase 1 stdout"

        mock_result_2 = MagicMock()
        mock_result_2.input_tokens = 250
        mock_result_2.output_tokens = 85
        mock_result_2.stdout = "phase 2 stdout"

        mock_runner.run = AsyncMock()
        mock_runner.run.side_effect = [mock_result_1, mock_result_2]

        # Mock GitOperations
        mock_git = MagicMock()
        mock_git.has_uncommitted_changes.return_value = False
        mock_git._run_git.return_value = MagicMock(stdout="")  # No unpushed changes to simplify
        mock_git_ops_class.return_value = mock_git

        # 3. Call target function
        result_state = await attempt_ci_fix(state)

        # 4. Verify token recording
        # stage_timestamps should have STAGE_CI with combined tokens (120+250=370, 45+85=130)
        assert "stage_timestamps" in result_state
        ci_stage = result_state["stage_timestamps"][STAGE_CI]
        assert ci_stage["input_tokens"] == 370
        assert ci_stage["output_tokens"] == 130

        # Check per-stage token usage map
        assert result_state["stage_token_usage"][STAGE_CI]["input_tokens"] == 370
        assert result_state["stage_token_usage"][STAGE_CI]["output_tokens"] == 130

        # Check aggregate token usage
        assert result_state["token_usage"]["input_tokens"] == 370
        assert result_state["token_usage"]["output_tokens"] == 130

    @pytest.mark.asyncio
    @patch("forge.workflow.nodes.ci_evaluator.JiraClient")
    @patch("forge.workflow.nodes.ci_evaluator.prepare_workspace")
    @patch("forge.workflow.nodes.ci_evaluator._fetch_ci_logs_and_artifacts")
    @patch("forge.workflow.nodes.ci_evaluator._collect_error_info")
    @patch("forge.workflow.nodes.ci_evaluator.load_prompt")
    @patch("forge.workflow.nodes.ci_evaluator.ContainerRunner")
    @patch("forge.workflow.nodes.ci_evaluator.GitOperations")
    @patch("forge.workflow.nodes.ci_evaluator.Workspace")
    async def test_attempt_ci_fix_records_estimated_tokens_on_fallback(
        self,
        _mock_workspace_class,
        mock_git_ops_class,
        mock_runner_class,
        mock_load_prompt,
        mock_collect_error_info,
        _mock_fetch_logs,
        mock_prepare_workspace,
        mock_jira_class,
        tmp_path,
    ):
        """Test fallback estimation when container returns no token metrics."""
        from forge.workflow.nodes.ci_evaluator import attempt_ci_fix
        from forge.workflow.stats import STAGE_CI

        state = create_base_state(
            ci_fix_attempt=1, ci_failed_checks=[{"name": "pytest", "conclusion": "failure"}]
        )

        mock_jira = MagicMock()
        mock_jira_close = AsyncMock()
        mock_jira.close = mock_jira_close
        mock_jira_class.return_value = mock_jira

        mock_prepare_workspace.return_value = (str(tmp_path), "main")
        mock_collect_error_info.return_value = "Some error details"
        mock_load_prompt.return_value = "Mocked Prompt " * 20  # length = 14 * 20 = 280

        fix_plan_file = tmp_path / ".forge" / "fix-plan.md"
        fix_plan_file.parent.mkdir(parents=True, exist_ok=True)
        fix_plan_file.write_text("Change line X to Y")

        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner

        # Phase 1 & 2 returns no tokens
        mock_result_1 = MagicMock()
        mock_result_1.input_tokens = 0
        mock_result_1.output_tokens = None
        mock_result_1.stdout = "phase 1 stdout " * 10  # length = 15 * 10 = 150

        mock_result_2 = MagicMock()
        mock_result_2.input_tokens = None
        mock_result_2.output_tokens = 0
        mock_result_2.stdout = "phase 2 stdout " * 10

        mock_runner.run = AsyncMock()
        mock_runner.run.side_effect = [mock_result_1, mock_result_2]

        mock_git = MagicMock()
        mock_git.has_uncommitted_changes.return_value = False
        mock_git._run_git.return_value = MagicMock(stdout="")
        mock_git_ops_class.return_value = mock_git

        result_state = await attempt_ci_fix(state)

        # Verify tokens are non-zero (estimated)
        assert "stage_timestamps" in result_state
        ci_stage = result_state["stage_timestamps"][STAGE_CI]
        assert ci_stage["input_tokens"] > 0
        assert ci_stage["output_tokens"] > 0

    @pytest.mark.asyncio
    @patch("forge.workflow.nodes.ci_evaluator.JiraClient")
    @patch("forge.workflow.nodes.ci_evaluator.prepare_workspace")
    @patch("forge.workflow.nodes.ci_evaluator._fetch_ci_logs_and_artifacts")
    @patch("forge.workflow.nodes.ci_evaluator._collect_error_info")
    @patch("forge.workflow.nodes.ci_evaluator.load_prompt")
    @patch("forge.workflow.nodes.ci_evaluator.ContainerRunner")
    @patch("forge.workflow.nodes.ci_evaluator.GitOperations")
    @patch("forge.workflow.nodes.ci_evaluator.Workspace")
    async def test_attempt_ci_fix_records_tokens_on_skipped_phase_2(
        self,
        mock_workspace_class,
        mock_git_ops_class,
        mock_runner_class,
        mock_load_prompt,
        mock_collect_error_info,
        mock_fetch_logs,
        mock_prepare_workspace,
        mock_jira_class,
        tmp_path,
    ):
        """Test token recording when Phase 2 is skipped (no fix plan file)."""
        from forge.workflow.nodes.ci_evaluator import attempt_ci_fix
        from forge.workflow.stats import STAGE_CI

        state = create_base_state(
            ci_fix_attempt=1, ci_failed_checks=[{"name": "pytest", "conclusion": "failure"}]
        )

        mock_jira = MagicMock()
        mock_jira.close = AsyncMock()
        mock_jira_class.return_value = mock_jira

        mock_prepare_workspace.return_value = (str(tmp_path), "main")
        mock_collect_error_info.return_value = "Some error details"
        mock_load_prompt.return_value = "Mocked Prompt"

        # We do NOT create fix plan file, so Phase 2 is skipped

        # Mock ContainerRunner and its run method for Phase 1
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner

        mock_result_1 = MagicMock()
        mock_result_1.input_tokens = 100
        mock_result_1.output_tokens = 50
        mock_result_1.stdout = "phase 1 stdout"

        mock_runner.run = AsyncMock()
        mock_runner.run.return_value = mock_result_1

        result_state = await attempt_ci_fix(state)

        # Verify tokens are recorded from Phase 1 only
        assert "stage_timestamps" in result_state
        ci_stage = result_state["stage_timestamps"][STAGE_CI]
        assert ci_stage["input_tokens"] == 100
        assert ci_stage["output_tokens"] == 50

    @pytest.mark.asyncio
    @patch("forge.workflow.nodes.ci_evaluator.JiraClient")
    @patch("forge.workflow.nodes.ci_evaluator.prepare_workspace")
    @patch("forge.workflow.nodes.ci_evaluator._fetch_ci_logs_and_artifacts")
    @patch("forge.workflow.nodes.ci_evaluator._collect_error_info")
    @patch("forge.workflow.nodes.ci_evaluator.load_prompt")
    @patch("forge.workflow.nodes.ci_evaluator.ContainerRunner")
    @patch("forge.workflow.nodes.ci_evaluator.GitOperations")
    @patch("forge.workflow.nodes.ci_evaluator.Workspace")
    async def test_attempt_ci_fix_records_tokens_on_phase_2_failure(
        self,
        mock_workspace_class,
        mock_git_ops_class,
        mock_runner_class,
        mock_load_prompt,
        mock_collect_error_info,
        mock_fetch_logs,
        mock_prepare_workspace,
        mock_jira_class,
        tmp_path,
    ):
        """Test token recording when Phase 2 fails (raises exception)."""
        from forge.workflow.nodes.ci_evaluator import attempt_ci_fix
        from forge.workflow.stats import STAGE_CI

        state = create_base_state(
            ci_fix_attempt=1, ci_failed_checks=[{"name": "pytest", "conclusion": "failure"}]
        )

        mock_jira = MagicMock()
        mock_jira.close = AsyncMock()
        mock_jira_class.return_value = mock_jira

        mock_prepare_workspace.return_value = (str(tmp_path), "main")
        mock_collect_error_info.return_value = "Some error details"
        mock_load_prompt.return_value = "Mocked Prompt"

        # We need fix plan file to exist so we don't skip the second phase
        fix_plan_file = tmp_path / ".forge" / "fix-plan.md"
        fix_plan_file.parent.mkdir(parents=True, exist_ok=True)
        fix_plan_file.write_text("Change line X to Y")

        # Mock ContainerRunner and its run method
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner

        mock_result_1 = MagicMock()
        mock_result_1.input_tokens = 100
        mock_result_1.output_tokens = 50
        mock_result_1.stdout = "phase 1 stdout"

        mock_runner.run = AsyncMock()
        # Phase 1 succeeds, but Phase 2 raises an exception
        mock_runner.run.side_effect = [mock_result_1, RuntimeError("Container failure")]

        result_state = await attempt_ci_fix(state)

        # Verify tokens from Phase 1 are still recorded even if Phase 2 failed with exception
        assert "stage_timestamps" in result_state
        ci_stage = result_state["stage_timestamps"][STAGE_CI]
        assert ci_stage["input_tokens"] == 100
        assert ci_stage["output_tokens"] == 50
