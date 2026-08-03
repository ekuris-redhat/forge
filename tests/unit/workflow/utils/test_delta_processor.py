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
