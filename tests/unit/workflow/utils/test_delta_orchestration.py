"""Unit tests for the active revision context state retrieval utility."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from forge.integrations.jira.client import JiraClient
from forge.integrations.agents import ForgeAgent
from forge.workflow.utils.delta_orchestration import (
    generate_revision_delta,
    get_current_revision_state,
    validate_delta_response,
)


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


@pytest.mark.asyncio
async def test_generate_revision_delta_success() -> None:
    """Test successful generation and parsing of delta-revision JSON."""
    state = {
        "ticket_key": "PROJ-123",
    }
    ticket_data = [
        {"key": "EPIC-1", "summary": "Epic One", "description": "Desc One"},
    ]
    feedback = "Add database migration details to Epic One"

    mock_agent = MagicMock(spec=ForgeAgent)
    # Mock return value with exact valid JSON structure
    mock_agent.run_task = AsyncMock(return_value="""
    {
        "to_create": [
            {"summary": "New Task", "description": "New Task description"}
        ],
        "to_edit": [
            {"key": "EPIC-1", "summary": "Epic One Revised", "description": "Revised Desc"}
        ],
        "to_archive": []
    }
    """)

    result = await generate_revision_delta(state, ticket_data, feedback, mock_agent)

    # Verify result structure
    assert result["to_create"] == [{"summary": "New Task", "description": "New Task description"}]
    assert result["to_edit"] == [{"key": "EPIC-1", "summary": "Epic One Revised", "description": "Revised Desc"}]
    assert result["to_archive"] == []

    # Verify agent.run_task call parameters and prompt rendering
    mock_agent.run_task.assert_called_once()
    call_kwargs = mock_agent.run_task.call_args.kwargs
    assert call_kwargs["task"] == "generate-revision-delta"
    assert call_kwargs["context"] == {"ticket_key": "PROJ-123"}

    prompt = call_kwargs["prompt"]
    assert "EPIC-1" in prompt
    assert "Epic One" in prompt
    assert "Add database migration" in prompt


@pytest.mark.asyncio
async def test_generate_revision_delta_markdown_wrapped() -> None:
    """Test parsing of delta JSON that is wrapped in markdown code blocks."""
    state = {"ticket_key": "PROJ-123"}
    ticket_data = []
    feedback = "Refactor everything"

    mock_agent = MagicMock(spec=ForgeAgent)
    mock_agent.run_task = AsyncMock(return_value="""
Here is the delta you requested:
```json
{
    "to_create": [],
    "to_edit": [],
    "to_archive": [{"key": "TASK-1"}]
}
```
Let me know if you need anything else!
""")

    result = await generate_revision_delta(state, ticket_data, feedback, mock_agent)

    assert result["to_create"] == []
    assert result["to_edit"] == []
    assert result["to_archive"] == [{"key": "TASK-1"}]


@pytest.mark.asyncio
async def test_generate_revision_delta_parsing_error() -> None:
    """Test robust fallback to empty delta when agent response is invalid JSON."""
    state = {"ticket_key": "PROJ-123"}
    ticket_data = []
    feedback = "Refactor everything"

    mock_agent = MagicMock(spec=ForgeAgent)
    mock_agent.run_task = AsyncMock(return_value="This is not JSON at all.")

    result = await generate_revision_delta(state, ticket_data, feedback, mock_agent)

    # Should fall back gracefully to empty lists
    assert result == {"to_create": [], "to_edit": [], "to_archive": []}


@pytest.mark.asyncio
async def test_generate_revision_delta_missing_keys_or_malformed() -> None:
    """Test that missing/invalid keys are safely normalized to empty lists."""
    state = {"ticket_key": "PROJ-123"}
    ticket_data = []
    feedback = "Refactor everything"

    mock_agent = MagicMock(spec=ForgeAgent)
    # JSON has to_create but missing to_edit and to_archive is not a list (malformed type)
    mock_agent.run_task = AsyncMock(return_value="""
    {
        "to_create": [{"summary": "Simple Task", "description": "Just build it"}],
        "to_archive": "this should be a list but is a string"
    }
    """)

    result = await generate_revision_delta(state, ticket_data, feedback, mock_agent)

    assert result["to_create"] == [{"summary": "Simple Task", "description": "Just build it"}]
    # Missing to_edit should be normalized to []
    assert result["to_edit"] == []
    # Invalid type to_archive should be normalized to []
    assert result["to_archive"] == []


def test_validate_delta_response_parent_epic_key_extraction() -> None:
    """Test that validate_delta_response extracts parent epic keys correctly from multiple possible JSON fields."""
    existing_keys = ["TASK-1", "TASK-2"]

    # Test cases with different parent key fields
    delta_cases = [
        {"to_create": [{"summary": "T1", "description": "D1", "parent_epic_key": "EPIC-101"}]},
        {"to_create": [{"summary": "T2", "description": "D2", "parent_key": "EPIC-102"}]},
        {"to_create": [{"summary": "T3", "description": "D3", "epic_key": "EPIC-103"}]},
        {"to_create": [{"summary": "T4", "description": "D4", "parent": "EPIC-104"}]},
        {"to_create": [{"summary": "T5", "description": "D5", "epic": "EPIC-105"}]},
        {"to_create": [{"summary": "T6", "description": "D6"}]},  # No parent key
    ]

    expected_parents = ["EPIC-101", "EPIC-102", "EPIC-103", "EPIC-104", "EPIC-105", None]

    for case, expected in zip(delta_cases, expected_parents):
        validated = validate_delta_response(case, existing_keys)
        assert len(validated["to_create"]) == 1
        assert validated["to_create"][0]["parent_epic_key"] == expected


def test_validate_delta_response_robustness() -> None:
    """Test that validate_delta_response is robust to malformed/non-dict items inside lists."""
    existing_keys = ["TASK-1", "TASK-2"]

    # Delta with malformed elements under to_create, to_edit, and to_archive
    delta = {
        "to_create": [
            "This is a string and not a dictionary, should be filtered out",
            None,
            {"summary": "Valid Task", "description": "Valid Desc", "parent_epic_key": "EPIC-1"}
        ],
        "to_edit": [
            "Another malformed item",
            {"key": "TASK-1", "summary": "Edited Task", "description": "Edited Desc"},
            {"key": "NON_EXISTENT", "summary": "Bad Key", "description": "Bad Desc"}  # Key not in existing_keys
        ],
        "to_archive": [
            12345,
            {"key": "TASK-2"},
            {"key": "NON_EXISTENT"}  # Key not in existing_keys
        ]
    }

    validated = validate_delta_response(delta, existing_keys)

    # Check that strings/none were filtered out from to_create
    assert len(validated["to_create"]) == 1
    assert validated["to_create"][0]["summary"] == "Valid Task"
    assert validated["to_create"][0]["parent_epic_key"] == "EPIC-1"

    # Check to_edit filtering
    assert len(validated["to_edit"]) == 1
    assert validated["to_edit"][0]["key"] == "TASK-1"
    assert validated["to_edit"][0]["summary"] == "Edited Task"

    # Check to_archive filtering
    assert len(validated["to_archive"]) == 1
    assert validated["to_archive"][0]["key"] == "TASK-2"


