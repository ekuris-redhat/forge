"""Unit tests for the Pydantic-based LLM delta processor and validation."""

import pytest
from pydantic import ValidationError

from forge.workflow.utils.delta_processor import (
    LLMDeltaResponse,
    validate_delta_response,
)


def test_successful_validation_all_fields() -> None:
    """Verify that a valid delta response with all fields is successfully validated."""
    payload = {
        "to_edit": [
            {
                "key": "TASK-1",
                "summary": "Updated Task 1 Summary",
                "description": "Updated Task 1 Description",
            }
        ],
        "to_create": [
            {
                "summary": "New Task Summary",
                "description": "New Task Description",
                "repo": "my-repo",
            }
        ],
        "to_archive": ["TASK-2"],
    }
    active_keys = ["TASK-1", "TASK-2", "TASK-3"]

    result = validate_delta_response(payload, active_keys)

    assert isinstance(result, LLMDeltaResponse)
    assert len(result.to_edit) == 1
    assert result.to_edit[0].key == "TASK-1"
    assert result.to_edit[0].summary == "Updated Task 1 Summary"
    assert result.to_edit[0].description == "Updated Task 1 Description"

    assert len(result.to_create) == 1
    assert result.to_create[0].summary == "New Task Summary"
    assert result.to_create[0].description == "New Task Description"
    assert result.to_create[0].repo == "my-repo"

    assert result.to_archive == ["TASK-2"]


def test_successful_validation_missing_optional_repo() -> None:
    """Verify that a valid delta response with missing optional repo in to_create is validated, defaulting repo to None."""
    payload = {
        "to_edit": [],
        "to_create": [
            {
                "summary": "New Task Summary",
                "description": "New Task Description",
            }
        ],
        "to_archive": [],
    }
    active_keys = []

    result = validate_delta_response(payload, active_keys)

    assert isinstance(result, LLMDeltaResponse)
    assert len(result.to_create) == 1
    assert result.to_create[0].summary == "New Task Summary"
    assert result.to_create[0].description == "New Task Description"
    assert result.to_create[0].repo is None


def test_rejection_for_extra_fields() -> None:
    """Verify that extra fields at any level of the payload are forbidden and raise ValidationError."""
    # Extra field at root level
    payload_extra_root = {
        "to_edit": [],
        "to_create": [],
        "to_archive": [],
        "extra_root_field": "not_allowed",
    }
    with pytest.raises(ValidationError) as exc_info:
        validate_delta_response(payload_extra_root, [])
    assert "extra_root_field" in str(exc_info.value)

    # Extra field inside to_edit
    payload_extra_edit = {
        "to_edit": [
            {
                "key": "TASK-1",
                "summary": "Summary",
                "description": "Desc",
                "invalid_field": "forbidden",
            }
        ],
        "to_create": [],
        "to_archive": [],
    }
    with pytest.raises(ValidationError) as exc_info:
        validate_delta_response(payload_extra_edit, ["TASK-1"])
    assert "invalid_field" in str(exc_info.value)

    # Extra field inside to_create
    payload_extra_create = {
        "to_edit": [],
        "to_create": [
            {
                "summary": "Summary",
                "description": "Desc",
                "invalid_field": "forbidden",
            }
        ],
        "to_archive": [],
    }
    with pytest.raises(ValidationError) as exc_info:
        validate_delta_response(payload_extra_create, [])
    assert "invalid_field" in str(exc_info.value)


def test_schema_rejection_for_malformed_formats() -> None:
    """Verify that incorrect type assignments (malformed formats) raise ValidationError."""
    # to_archive is not a list of strings
    payload_bad_archive = {
        "to_edit": [],
        "to_create": [],
        "to_archive": [{"key": "TASK-1"}],  # expected list of str, got list of dict
    }
    with pytest.raises(ValidationError):
        validate_delta_response(payload_bad_archive, ["TASK-1"])

    # to_edit is not a list of objects
    payload_bad_edit = {
        "to_edit": ["TASK-1"],  # expected list of dict, got list of str
        "to_create": [],
        "to_archive": [],
    }
    with pytest.raises(ValidationError):
        validate_delta_response(payload_bad_edit, ["TASK-1"])


def test_rejection_of_unrecognized_keys_in_to_edit() -> None:
    """Verify ValueError is raised if a key in to_edit is not present in active_keys (SC-001 Edge Case)."""
    payload = {
        "to_edit": [
            {
                "key": "TASK-UNKNOWN",
                "summary": "Updated Summary",
                "description": "Updated Description",
            }
        ],
        "to_create": [],
        "to_archive": [],
    }
    active_keys = ["TASK-1", "TASK-2"]

    with pytest.raises(ValueError) as exc_info:
        validate_delta_response(payload, active_keys)

    assert "TASK-UNKNOWN" in str(exc_info.value)
    assert "to_edit" in str(exc_info.value)


def test_rejection_of_unrecognized_keys_in_to_archive() -> None:
    """Verify ValueError is raised if a key in to_archive is not present in active_keys (SC-001 Edge Case)."""
    payload = {
        "to_edit": [],
        "to_create": [],
        "to_archive": ["TASK-UNKNOWN"],
    }
    active_keys = ["TASK-1", "TASK-2"]

    with pytest.raises(ValueError) as exc_info:
        validate_delta_response(payload, active_keys)

    assert "TASK-UNKNOWN" in str(exc_info.value)
    assert "to_archive" in str(exc_info.value)


from unittest.mock import AsyncMock, MagicMock
from forge.integrations.jira.client import JiraClient
from forge.workflow.utils.delta_processor import apply_delta_updates


@pytest.fixture
def mock_jira_client() -> MagicMock:
    """Create a mock Jira client."""
    client = MagicMock(spec=JiraClient)
    client.archive_issue = AsyncMock()
    client.update_summary_and_description = AsyncMock()
    client.create_epic = AsyncMock()
    client.create_task = AsyncMock()
    client.get_issue = AsyncMock()
    client.get_labels = AsyncMock(return_value=[])
    client.add_labels = AsyncMock()
    client.remove_labels = AsyncMock()
    client.get_project_default_repo = AsyncMock(return_value="owner/default-repo")
    return client


@pytest.mark.asyncio
async def test_apply_delta_updates_epic_success(mock_jira_client: MagicMock) -> None:
    """Verify successful application of an epic delta and corresponding state updates."""
    payload = {
        "to_edit": [
            {
                "key": "EPIC-1",
                "summary": "Updated Epic 1 Summary",
                "description": "Updated Epic 1 Description",
                "repo": "owner/epic-repo",
            }
        ],
        "to_create": [
            {
                "summary": "New Epic Summary",
                "description": "New Epic Description",
                "repo": "owner/new-repo",
            }
        ],
        "to_archive": ["EPIC-2"],
    }
    active_keys = ["EPIC-1", "EPIC-2", "EPIC-PRESERVED"]
    delta = validate_delta_response(payload, active_keys)

    state = {
        "ticket_key": "FEAT-1",
        "epic_keys": ["EPIC-1", "EPIC-2", "EPIC-PRESERVED"],
    }

    mock_jira_client.create_epic.return_value = "EPIC-3"

    updated_state = await apply_delta_updates(
        jira=mock_jira_client,
        delta=delta,
        state=state,
        level="epic",
        project_key="PROJ",
    )

    # Verify state updates
    assert updated_state["epic_keys"] == ["EPIC-1", "EPIC-PRESERVED", "EPIC-3"]
    # Verify transactional preservation: original state must be untouched
    assert state["epic_keys"] == ["EPIC-1", "EPIC-2", "EPIC-PRESERVED"]

    # Verify Jira sequential operations
    mock_jira_client.archive_issue.assert_called_once_with("EPIC-2", archive_subtasks=True)
    mock_jira_client.update_summary_and_description.assert_called_once_with(
        "EPIC-1", "Updated Epic 1 Summary", "Updated Epic 1 Description"
    )
    mock_jira_client.create_epic.assert_called_once_with(
        project_key="PROJ",
        summary="New Epic Summary",
        description="New Epic Description",
        parent_key="FEAT-1",
        labels=["forge:managed", "forge:parent:FEAT-1", "repo:owner/new-repo"],
    )


@pytest.mark.asyncio
async def test_apply_delta_updates_task_success(mock_jira_client: MagicMock) -> None:
    """Verify successful application of a task delta and corresponding state updates."""
    payload = {
        "to_edit": [
            {
                "key": "TASK-1",
                "summary": "Updated Task 1 Summary",
                "description": "Updated Task 1 Description",
                "repo": "owner/updated-task-repo",
            }
        ],
        "to_create": [
            {
                "summary": "New Task Summary",
                "description": "New Task Description",
                "repo": "owner/new-task-repo",
            }
        ],
        "to_archive": ["TASK-2"],
    }
    active_keys = ["TASK-1", "TASK-2", "TASK-PRESERVED"]
    delta = validate_delta_response(payload, active_keys)

    state = {
        "ticket_key": "FEAT-1",
        "epic_keys": ["EPIC-1"],
        "task_keys": ["TASK-1", "TASK-2", "TASK-PRESERVED"],
        "tasks_by_repo": {
            "owner/old-repo": ["TASK-1", "TASK-2"],
            "owner/preserved-repo": ["TASK-PRESERVED"],
        },
    }

    mock_jira_client.create_task.return_value = "TASK-3"

    # Mock get_issue to return a task issue with a parent epic key
    issue_mock = MagicMock()
    issue_mock.parent_key = "EPIC-1"
    mock_jira_client.get_issue.return_value = issue_mock

    updated_state = await apply_delta_updates(
        jira=mock_jira_client,
        delta=delta,
        state=state,
        level="task",
        project_key="PROJ",
    )

    # Verify state updates
    assert updated_state["task_keys"] == ["TASK-1", "TASK-PRESERVED", "TASK-3"]
    assert updated_state["tasks_by_repo"] == {
        "owner/updated-task-repo": ["TASK-1"],
        "owner/preserved-repo": ["TASK-PRESERVED"],
        "owner/new-task-repo": ["TASK-3"],
    }

    # Verify original state remains untouched
    assert state["task_keys"] == ["TASK-1", "TASK-2", "TASK-PRESERVED"]
    assert state["tasks_by_repo"] == {
        "owner/old-repo": ["TASK-1", "TASK-2"],
        "owner/preserved-repo": ["TASK-PRESERVED"],
    }

    # Verify Jira sequential operations
    mock_jira_client.archive_issue.assert_called_once_with("TASK-2", archive_subtasks=False)
    mock_jira_client.update_summary_and_description.assert_called_once_with(
        "TASK-1", "Updated Task 1 Summary", "Updated Task 1 Description"
    )
    mock_jira_client.create_task.assert_called_once_with(
        project_key="PROJ",
        summary="New Task Summary",
        description="New Task Description",
        parent_key="EPIC-1",
        labels=["forge:managed", "forge:parent:FEAT-1", "repo:owner/new-task-repo"],
    )


@pytest.mark.asyncio
async def test_apply_delta_updates_failure_rolls_back_state(mock_jira_client: MagicMock) -> None:
    """Verify that a failure during sequential operations leaves state untouched and propagates error."""
    payload = {
        "to_edit": [
            {
                "key": "EPIC-1",
                "summary": "Updated Epic 1 Summary",
                "description": "Updated Epic 1 Description",
            }
        ],
        "to_create": [
            {
                "summary": "New Epic Summary",
                "description": "New Epic Description",
            }
        ],
        "to_archive": ["EPIC-2"],
    }
    active_keys = ["EPIC-1", "EPIC-2", "EPIC-PRESERVED"]
    delta = validate_delta_response(payload, active_keys)

    state = {
        "ticket_key": "FEAT-1",
        "epic_keys": ["EPIC-1", "EPIC-2", "EPIC-PRESERVED"],
    }

    # Simulate failure on the second operation (edit)
    mock_jira_client.update_summary_and_description.side_effect = RuntimeError("Jira Edit Failure")

    with pytest.raises(RuntimeError, match="Jira Edit Failure"):
        await apply_delta_updates(
            jira=mock_jira_client,
            delta=delta,
            state=state,
            level="epic",
            project_key="PROJ",
        )

    # Verify state is completely untouched
    assert state["epic_keys"] == ["EPIC-1", "EPIC-2", "EPIC-PRESERVED"]
    # archive should have been called, but edit failed and create was never called
    mock_jira_client.archive_issue.assert_called_once_with("EPIC-2", archive_subtasks=True)
    mock_jira_client.create_epic.assert_not_called()
