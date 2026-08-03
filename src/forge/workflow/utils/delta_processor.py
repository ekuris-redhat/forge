"""Pydantic models and validation logic for LLM delta update responses."""

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class EditTicket(BaseModel):
    """Pydantic model representing an item in the to_edit list of a delta response."""

    model_config = ConfigDict(extra="forbid")

    key: str
    summary: str
    description: str


class CreateTicket(BaseModel):
    """Pydantic model representing an item in the to_create list of a delta response."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    description: str
    repo: str | None = None


class LLMDeltaResponse(BaseModel):
    """Pydantic model representing the overall structure of an LLM delta response."""

    model_config = ConfigDict(extra="forbid")

    to_edit: list[EditTicket] = Field(default_factory=list)
    to_create: list[CreateTicket] = Field(default_factory=list)
    to_archive: list[str] = Field(default_factory=list)


def validate_delta_response(
    response_dict: dict[str, Any], active_keys: list[str]
) -> LLMDeltaResponse:
    """Parses and validates the input dictionary against LLMDeltaResponse.

    Args:
        response_dict: Dictionary matching the LLMDeltaResponse schema.
        active_keys: List of valid ticket keys currently active.

    Returns:
        LLMDeltaResponse: Validated Pydantic model instance.

    Raises:
        ValidationError: If the response_dict does not conform to the LLMDeltaResponse schema.
        ValueError: If any key in to_edit or to_archive is not present in active_keys.
    """
    # Parse and validate standard schema using Pydantic
    delta = LLMDeltaResponse.model_validate(response_dict)

    # Validate that all targeted keys for edit or archive are within active_keys
    active_keys_set = set(active_keys)

    for edit_item in delta.to_edit:
        if edit_item.key not in active_keys_set:
            raise ValueError(
                f"Validation error: Key '{edit_item.key}' in to_edit is not an active ticket key."
            )

    for archive_key in delta.to_archive:
        if archive_key not in active_keys_set:
            raise ValueError(
                f"Validation error: Key '{archive_key}' in to_archive is not an active ticket key."
            )

    return delta
