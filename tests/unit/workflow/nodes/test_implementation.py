"""Unit tests for task implementation node - Jira status comments."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.workflow.feature.state import create_initial_feature_state
from forge.workflow.nodes.implementation import implement_task


def create_mock_jira_client():
    """Create a mock JiraClient with required methods."""
    mock = MagicMock()
    mock.close = AsyncMock()
    mock.add_comment = AsyncMock()
    mock.get_issue = AsyncMock()
    
    # Mock issue with description and summary
    mock_issue = MagicMock()
    mock_issue.description = "Task description"
    mock_issue.summary = "Task summary"
    mock.get_issue.return_value = mock_issue
    
    return mock


def create_mock_container_runner():
    """Create a mock ContainerRunner."""
    mock = MagicMock()
    
    # Mock successful result by default
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.error_message = None
    
    mock.run = AsyncMock(return_value=mock_result)
    return mock, mock_result


class TestImplementTaskStatusComments:
    """Test cases for task implementation status comments."""

    @pytest.mark.asyncio
    async def test_implement_task_posts_start_comment(self):
        """Should post start comment when task implementation begins."""
        mock_jira = create_mock_jira_client()
        mock_runner, mock_result = create_mock_container_runner()

        state = create_initial_feature_state(
            ticket_key="FEAT-123",
            current_repo="owner/test-repo",
            task_keys=["TASK-1"],
        )
        state["workspace_path"] = "/tmp/test-workspace"
        state["current_task_key"] = "TASK-1"
        state["tasks_by_repo"] = {"owner/test-repo": ["TASK-1"]}

        with (
            patch("forge.workflow.nodes.implementation.JiraClient", return_value=mock_jira),
            patch("forge.workflow.nodes.implementation.ContainerRunner", return_value=mock_runner),
        ):
            result = await implement_task(state)

        # Verify start comment was posted
        assert mock_jira.add_comment.call_count >= 1
        start_comment_call = mock_jira.add_comment.call_args_list[0]
        assert start_comment_call[0][0] == "TASK-1"
        assert start_comment_call[0][1] == "🔨 Forge is implementing this task."

    @pytest.mark.asyncio
    async def test_implement_task_posts_completion_comment_on_success(self):
        """Should post completion comment when task implementation succeeds."""
        mock_jira = create_mock_jira_client()
        mock_runner, mock_result = create_mock_container_runner()
        mock_result.success = True

        state = create_initial_feature_state(
            ticket_key="FEAT-123",
            current_repo="owner/test-repo",
            task_keys=["TASK-1"],
        )
        state["workspace_path"] = "/tmp/test-workspace"
        state["current_task_key"] = "TASK-1"
        state["tasks_by_repo"] = {"owner/test-repo": ["TASK-1"]}

        with (
            patch("forge.workflow.nodes.implementation.JiraClient", return_value=mock_jira),
            patch("forge.workflow.nodes.implementation.ContainerRunner", return_value=mock_runner),
        ):
            result = await implement_task(state)

        # Verify both start and completion comments were posted
        assert mock_jira.add_comment.call_count == 2
        
        # Verify start comment
        start_comment_call = mock_jira.add_comment.call_args_list[0]
        assert start_comment_call[0][0] == "TASK-1"
        assert start_comment_call[0][1] == "🔨 Forge is implementing this task."
        
        # Verify completion comment
        completion_comment_call = mock_jira.add_comment.call_args_list[1]
        assert completion_comment_call[0][0] == "TASK-1"
        assert completion_comment_call[0][1] == "✅ Implementation complete. Running local code review before PR."

    @pytest.mark.asyncio
    async def test_implement_task_no_completion_comment_on_failure(self):
        """Should NOT post completion comment when task implementation fails."""
        mock_jira = create_mock_jira_client()
        mock_runner, mock_result = create_mock_container_runner()
        mock_result.success = False
        mock_result.error_message = "Container failed"

        state = create_initial_feature_state(
            ticket_key="FEAT-123",
            current_repo="owner/test-repo",
            task_keys=["TASK-1"],
        )
        state["workspace_path"] = "/tmp/test-workspace"
        state["current_task_key"] = "TASK-1"
        state["tasks_by_repo"] = {"owner/test-repo": ["TASK-1"]}

        with (
            patch("forge.workflow.nodes.implementation.JiraClient", return_value=mock_jira),
            patch("forge.workflow.nodes.implementation.ContainerRunner", return_value=mock_runner),
            patch("forge.workflow.nodes.implementation.notify_error", new=AsyncMock()),
        ):
            result = await implement_task(state)

        # Verify only start comment was posted, NOT completion comment
        assert mock_jira.add_comment.call_count == 1
        start_comment_call = mock_jira.add_comment.call_args_list[0]
        assert start_comment_call[0][0] == "TASK-1"
        assert start_comment_call[0][1] == "🔨 Forge is implementing this task."
        
        # Verify error state
        assert result["last_error"] == "Container failed"

    @pytest.mark.asyncio
    async def test_implement_task_multiple_tasks_independent_comments(self):
        """Should post independent start/completion comments for each task."""
        mock_jira = create_mock_jira_client()
        mock_runner, mock_result = create_mock_container_runner()
        mock_result.success = True

        state = create_initial_feature_state(
            ticket_key="FEAT-123",
            current_repo="owner/test-repo",
            task_keys=["TASK-1", "TASK-2"],
        )
        state["workspace_path"] = "/tmp/test-workspace"
        state["tasks_by_repo"] = {"owner/test-repo": ["TASK-1", "TASK-2"]}
        state["implemented_tasks"] = []

        # Implement first task
        with (
            patch("forge.workflow.nodes.implementation.JiraClient", return_value=mock_jira),
            patch("forge.workflow.nodes.implementation.ContainerRunner", return_value=mock_runner),
        ):
            result1 = await implement_task(state)

        # Verify first task got start and completion comments
        assert mock_jira.add_comment.call_count == 2
        assert mock_jira.add_comment.call_args_list[0][0][0] == "TASK-1"
        assert mock_jira.add_comment.call_args_list[1][0][0] == "TASK-1"

        # Reset mock for second task
        mock_jira.add_comment.reset_mock()
        mock_jira2 = create_mock_jira_client()
        mock_runner2, mock_result2 = create_mock_container_runner()
        mock_result2.success = True

        # Update state for second task
        state2 = result1.copy()
        state2["current_task_key"] = None  # Let the node find the next task

        # Implement second task
        with (
            patch("forge.workflow.nodes.implementation.JiraClient", return_value=mock_jira2),
            patch("forge.workflow.nodes.implementation.ContainerRunner", return_value=mock_runner2),
        ):
            result2 = await implement_task(state2)

        # Verify second task got its own start and completion comments
        assert mock_jira2.add_comment.call_count == 2
        assert mock_jira2.add_comment.call_args_list[0][0][0] == "TASK-2"
        assert mock_jira2.add_comment.call_args_list[1][0][0] == "TASK-2"


class TestImplementTaskErrorHandling:
    """Test cases for error handling in task implementation."""

    @pytest.mark.asyncio
    async def test_implement_task_continues_on_comment_failure(self, caplog):
        """Should continue workflow execution if status comment fails."""
        mock_jira = create_mock_jira_client()
        # Make add_comment fail but workflow should continue
        mock_jira.add_comment = AsyncMock(side_effect=Exception("Jira API error"))
        
        mock_runner, mock_result = create_mock_container_runner()
        mock_result.success = True

        state = create_initial_feature_state(
            ticket_key="FEAT-123",
            current_repo="owner/test-repo",
            task_keys=["TASK-1"],
        )
        state["workspace_path"] = "/tmp/test-workspace"
        state["current_task_key"] = "TASK-1"
        state["tasks_by_repo"] = {"owner/test-repo": ["TASK-1"]}

        with (
            patch("forge.workflow.nodes.implementation.JiraClient", return_value=mock_jira),
            patch("forge.workflow.nodes.implementation.ContainerRunner", return_value=mock_runner),
        ):
            result = await implement_task(state)

        # Verify workflow continued despite comment failure
        assert "TASK-1" in result["implemented_tasks"]
        assert result["last_error"] is None
        
        # Verify error was logged
        assert any(
            "Failed to post status comment to TASK-1" in record.message
            for record in caplog.records
        )
