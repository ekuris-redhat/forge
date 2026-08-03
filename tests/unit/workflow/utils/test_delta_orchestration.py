"""Unit tests for the active revision context state retrieval utility."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from forge.integrations.jira.client import JiraClient
from forge.workflow.utils.delta_orchestration import get_current_revision_state


@pytest.fixture
def mock_jira_client() -> MagicMock:
    """Create a mock Jira client."""
    client = MagicMock(spec=JiraClient)
    client.get_issue = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_get_current_revision_state_epic_level(mock_jira_client: MagicMock) -> None:
    """Test retrieving revision state for epic level."""
    state = {
        "epic_keys": ["EPIC-1", "EPIC-2"],
    }

    # Set up mock issue details
    issue_1 = MagicMock()
    issue_1.summary = "Epic One Summary"
    issue_1.description = "Epic One Description"

    issue_2 = MagicMock()
    issue_2.summary = "Epic Two Summary"
    issue_2.description = "Epic Two Description"

    # Define mock return values based on issue key
    async def side_effect(key: str) -> MagicMock:
        if key == "EPIC-1":
            return issue_1
        if key == "EPIC-2":
            return issue_2
        raise ValueError(f"Unexpected key {key}")

    mock_jira_client.get_issue.side_effect = side_effect

    result = await get_current_revision_state(state, "epic", mock_jira_client)

    assert len(result) == 2
    assert result[0] == {
        "key": "EPIC-1",
        "summary": "Epic One Summary",
        "description": "Epic One Description",
    }
    assert result[1] == {
        "key": "EPIC-2",
        "summary": "Epic Two Summary",
        "description": "Epic Two Description",
    }

    assert mock_jira_client.get_issue.call_count == 2
    mock_jira_client.get_issue.assert_any_call("EPIC-1")
    mock_jira_client.get_issue.assert_any_call("EPIC-2")


@pytest.mark.asyncio
async def test_get_current_revision_state_task_level_from_keys(mock_jira_client: MagicMock) -> None:
    """Test retrieving revision state for task level using state['task_keys']."""
    state = {
        "task_keys": ["TASK-1", "TASK-2"],
        "tasks_by_repo": {
            "repo-a": ["TASK-3"],
        },
    }

    issue_1 = MagicMock()
    issue_1.summary = "Task One"
    issue_1.description = "Task One Desc"

    issue_2 = MagicMock()
    issue_2.summary = "Task Two"
    issue_2.description = "Task Two Desc"

    async def side_effect(key: str) -> MagicMock:
        if key == "TASK-1":
            return issue_1
        if key == "TASK-2":
            return issue_2
        raise ValueError(f"Unexpected key {key}")

    mock_jira_client.get_issue.side_effect = side_effect

    result = await get_current_revision_state(state, "task", mock_jira_client)

    assert len(result) == 2
    assert result[0] == {
        "key": "TASK-1",
        "summary": "Task One",
        "description": "Task One Desc",
    }
    assert result[1] == {
        "key": "TASK-2",
        "summary": "Task Two",
        "description": "Task Two Desc",
    }


@pytest.mark.asyncio
async def test_get_current_revision_state_task_level_from_repo_values(
    mock_jira_client: MagicMock,
) -> None:
    """Test retrieving revision state for task level falling back to state['tasks_by_repo']."""
    state = {
        "task_keys": [],  # Empty
        "tasks_by_repo": {
            "repo-a": ["TASK-10", "TASK-20"],
            "repo-b": ["TASK-20", "TASK-30"],  # TASK-20 is duplicated to verify deduplication
        },
    }

    issues = {
        "TASK-10": MagicMock(summary="T10", description="Desc10"),
        "TASK-20": MagicMock(summary="T20", description="Desc20"),
        "TASK-30": MagicMock(summary="T30", description="Desc30"),
    }

    async def side_effect(key: str) -> MagicMock:
        return issues[key]

    mock_jira_client.get_issue.side_effect = side_effect

    result = await get_current_revision_state(state, "task", mock_jira_client)

    # Deduped and extracted in insertion order from tasks_by_repo values
    assert len(result) == 3
    assert [r["key"] for r in result] == ["TASK-10", "TASK-20", "TASK-30"]
    assert result[0] == {"key": "TASK-10", "summary": "T10", "description": "Desc10"}


@pytest.mark.asyncio
async def test_get_current_revision_state_missing_or_empty_description(
    mock_jira_client: MagicMock,
) -> None:
    """Test safe handling of missing, None, or empty description fields."""
    state = {
        "epic_keys": ["EPIC-EMPTY", "EPIC-NONE", "EPIC-MISSING"],
    }

    issue_empty = MagicMock()
    issue_empty.summary = "Empty Summary"
    issue_empty.description = ""

    issue_none = MagicMock()
    issue_none.summary = "None Summary"
    issue_none.description = None

    issue_missing = MagicMock(spec=[])  # Spec has no description attribute
    issue_missing.summary = "Missing Summary"

    async def side_effect(key: str) -> MagicMock:
        if key == "EPIC-EMPTY":
            return issue_empty
        if key == "EPIC-NONE":
            return issue_none
        if key == "EPIC-MISSING":
            return issue_missing
        raise ValueError(f"Unexpected key {key}")

    mock_jira_client.get_issue.side_effect = side_effect

    result = await get_current_revision_state(state, "epic", mock_jira_client)

    assert len(result) == 3
    assert result[0] == {"key": "EPIC-EMPTY", "summary": "Empty Summary", "description": ""}
    assert result[1] == {"key": "EPIC-NONE", "summary": "None Summary", "description": ""}
    assert result[2] == {"key": "EPIC-MISSING", "summary": "Missing Summary", "description": ""}


@pytest.mark.asyncio
async def test_get_current_revision_state_unsupported_level(mock_jira_client: MagicMock) -> None:
    """Test that a ValueError is raised for an unsupported level."""
    state = {
        "epic_keys": ["EPIC-1"],
    }
    with pytest.raises(ValueError, match="Unsupported level: invalid"):
        await get_current_revision_state(state, "invalid", mock_jira_client)


@pytest.mark.asyncio
async def test_get_current_revision_state_partial_failure(mock_jira_client: MagicMock) -> None:
    """Test that individual fetch failures are handled gracefully without failing the entire batch."""
    state = {
        "epic_keys": ["EPIC-SUCCESS", "EPIC-FAIL"],
    }

    issue_success = MagicMock()
    issue_success.summary = "Success Epic"
    issue_success.description = "Success Desc"

    async def side_effect(key: str) -> MagicMock:
        if key == "EPIC-SUCCESS":
            return issue_success
        raise RuntimeError("Jira API error")

    mock_jira_client.get_issue.side_effect = side_effect

    result = await get_current_revision_state(state, "epic", mock_jira_client)

    assert len(result) == 1
    assert result[0] == {
        "key": "EPIC-SUCCESS",
        "summary": "Success Epic",
        "description": "Success Desc",
    }


@pytest.mark.asyncio
async def test_get_current_revision_state_concurrent_execution(mock_jira_client: MagicMock) -> None:
    """Verify that asyncio.gather is used and fetches are performed concurrently."""
    state = {
        "epic_keys": ["EPIC-1", "EPIC-2"],
    }

    events = []

    async def side_effect(key: str) -> MagicMock:
        events.append(f"start-{key}")
        await asyncio.sleep(0.05)
        events.append(f"end-{key}")
        issue = MagicMock()
        issue.summary = f"Summary {key}"
        issue.description = f"Description {key}"
        return issue

    mock_jira_client.get_issue.side_effect = side_effect

    # This should run them concurrently, meaning both should start before either ends
    result = await get_current_revision_state(state, "epic", mock_jira_client)

    assert len(result) == 2
    # If concurrent, both start-events must occur before the end-events
    assert events[0].startswith("start-")
    assert events[1].startswith("start-")
    assert events[2].startswith("end-")
    assert events[3].startswith("end-")
