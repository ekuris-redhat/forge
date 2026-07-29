"""Configurable Langfuse trace tag and metadata fields.

Admins configure which fields to include as tags/metadata via env vars:
  LANGFUSE_TRACE_TAGS=ticket_type,project_id,workflow_step
  LANGFUSE_TRACE_METADATA=ticket_key,ticket_type,project_id,retry_count
"""

import logging
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class TracingField(StrEnum):
    """Available fields for Langfuse trace tags and metadata."""

    TICKET_KEY = "ticket_key"
    TICKET_TYPE = "ticket_type"
    PROJECT_ID = "project_id"
    WORKFLOW_STEP = "workflow_step"
    REPO = "repo"
    PR_NUMBER = "pr_number"
    CI_STATUS = "ci_status"
    EVENT_SOURCE = "event_source"
    EVENT_TYPE = "event_type"
    RETRY_COUNT = "retry_count"
    SYSTEM_PROMPT_LENGTH = "system_prompt_length"
    LLM_MODEL = "llm_model"

    @property
    def tag_eligible(self) -> bool:
        return self not in _METADATA_ONLY_FIELDS


_METADATA_ONLY_FIELDS = frozenset({TracingField.RETRY_COUNT, TracingField.SYSTEM_PROMPT_LENGTH})


def resolve_field(field: TracingField, state: dict[str, Any]) -> str | None:
    """Resolve a single tracing field from workflow state.

    Args:
        field: The field to resolve.
        state: Workflow state dict.

    Returns:
        String value or None if the data isn't available.
    """
    resolver = _RESOLVERS.get(field)
    if resolver is None:
        return None
    return resolver(state)


def _resolve_ticket_key(state: dict[str, Any]) -> str | None:
    val = state.get("ticket_key")
    return str(val) if val is not None else None


def _resolve_ticket_type(state: dict[str, Any]) -> str | None:
    val = state.get("ticket_type")
    return str(val) if val is not None else None


def _resolve_project_id(state: dict[str, Any]) -> str | None:
    ticket_key = state.get("ticket_key")
    if not ticket_key or "-" not in str(ticket_key):
        return None
    return str(ticket_key).rsplit("-", 1)[0]


def _resolve_workflow_step(state: dict[str, Any]) -> str | None:
    current_node = state.get("current_node")
    if current_node is None:
        return None

    node_str = str(current_node)

    # Determine workflow_stage_or_node
    # If the active operation is decompose_epics or generate_tasks, categorize under breakdown flow
    if node_str in ("decompose_epics", "generate_tasks"):
        stage_or_node = "decompose_epics" if node_str == "decompose_epics" else "generate_tasks"
    else:
        stage_or_node = node_str

    # Determine operation_type
    is_question = state.get("is_question", False)
    is_revision = state.get("is_revision", False)
    revision_requested = state.get("revision_requested", False)

    if is_question or "qa" in node_str or "question" in node_str:
        operation_type = "question_asking"
    elif (
        is_revision
        or revision_requested
        or node_str.startswith("regenerate_")
        or "revise" in node_str
    ):
        operation_type = "revision"
    elif node_str in ("decompose_epics", "generate_tasks"):
        operation_type = "breakdown"
    elif "gate" in node_str or "approval" in node_str:
        operation_type = "approval_gate"
    else:
        operation_type = "initial_generation"

    # Determine artifact_type
    # Map based on node name, task, or state properties
    # Target artifacts: spec, prd, plan, tasks, epic_breakdown, etc.
    if state.get("artifact_type") is not None:
        artifact_type = str(state["artifact_type"])
    else:
        artifact_type = "unknown"
        task = state.get("task", "") or ""
        task_str = str(task).lower()

        # Analyze state/node to map artifact type
        if "spec" in node_str or "spec" in task_str:
            artifact_type = "spec"
        elif "prd" in node_str or "prd" in task_str:
            artifact_type = "prd"
        elif "plan" in node_str or "plan" in task_str:
            artifact_type = "plan"
        elif "task" in node_str or "task" in task_str:
            artifact_type = "tasks"
        elif (
            "epic" in node_str
            or "epic" in task_str
            or "breakdown" in node_str
            or "breakdown" in task_str
            or node_str == "decompose_epics"
        ):
            artifact_type = "epic_breakdown"
        elif node_str == "generate_tasks":
            artifact_type = "tasks"

    # Format base label: [workflow_stage_or_node]:[operation_type]:[artifact_type]
    label = f"{stage_or_node}:{operation_type}:{artifact_type}"

    # Appended when retry_count is greater than 0
    retry_count = state.get("retry_count", 0)
    try:
        retry_int = int(retry_count) if retry_count is not None else 0
    except (ValueError, TypeError):
        retry_int = 0

    if retry_int > 0:
        label += f":attempt-{retry_int}"

    return label


def _resolve_repo(state: dict[str, Any]) -> str | None:
    val = state.get("repo") or state.get("current_repo")
    return str(val) if val is not None else None


def _resolve_pr_number(state: dict[str, Any]) -> str | None:
    val = state.get("pr_number") or state.get("current_pr_number")
    return str(val) if val is not None else None


def _resolve_ci_status(state: dict[str, Any]) -> str | None:
    val = state.get("ci_status")
    return str(val) if val is not None else None


def _resolve_event_source(state: dict[str, Any]) -> str | None:
    val = state.get("event_source")
    if val is not None:
        return str(val)
    ctx = state.get("context")
    if isinstance(ctx, dict):
        val = ctx.get("source")
        if val is not None:
            return str(val)
    return None


def _resolve_event_type(state: dict[str, Any]) -> str | None:
    val = state.get("event_type")
    return str(val) if val is not None else None


def _resolve_retry_count(state: dict[str, Any]) -> str | None:
    val = state.get("retry_count")
    return str(val) if val is not None else None


def _resolve_system_prompt_length(state: dict[str, Any]) -> str | None:
    val = state.get("system_prompt_length")
    return str(val) if val is not None else None


def _resolve_llm_model(state: dict[str, Any]) -> str | None:
    val = state.get("llm_model")
    return str(val) if val is not None else None


_RESOLVERS: dict[TracingField, Any] = {
    TracingField.TICKET_KEY: _resolve_ticket_key,
    TracingField.TICKET_TYPE: _resolve_ticket_type,
    TracingField.PROJECT_ID: _resolve_project_id,
    TracingField.WORKFLOW_STEP: _resolve_workflow_step,
    TracingField.REPO: _resolve_repo,
    TracingField.PR_NUMBER: _resolve_pr_number,
    TracingField.CI_STATUS: _resolve_ci_status,
    TracingField.EVENT_SOURCE: _resolve_event_source,
    TracingField.EVENT_TYPE: _resolve_event_type,
    TracingField.RETRY_COUNT: _resolve_retry_count,
    TracingField.SYSTEM_PROMPT_LENGTH: _resolve_system_prompt_length,
    TracingField.LLM_MODEL: _resolve_llm_model,
}


def parse_trace_fields(config_str: str, *, allow_tags: bool) -> list[TracingField]:
    """Parse a comma-separated config string into validated TracingField list.

    Args:
        config_str: Comma-separated field names (e.g., "ticket_key,ticket_type").
        allow_tags: If True, validates tag eligibility; if False, allows all fields.

    Returns:
        List of valid TracingField values. Invalid names are warned and skipped.
    """
    if not config_str or not config_str.strip():
        return []

    available = ", ".join(sorted(f.value for f in TracingField))
    result: list[TracingField] = []

    for raw in config_str.split(","):
        name = raw.strip()
        if not name:
            continue

        try:
            field = TracingField(name)
        except ValueError:
            logger.warning(
                "Invalid Langfuse trace field '%s' - not a recognized field name. Available: %s",
                name,
                available,
            )
            continue

        if allow_tags and not field.tag_eligible:
            logger.warning(
                "Field '%s' is not eligible for tags (quantitative field) - skipping",
                name,
            )
            continue

        result.append(field)

    return result


def resolve_trace_fields(state: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Resolve configured tracing fields from workflow state.

    Reads the configured tag/metadata fields from settings, resolves each
    against the state dict, and returns the results. Fields that resolve
    to None are silently omitted.

    Args:
        state: Workflow state dict containing trace data.

    Returns:
        (tags, metadata) — tags is a list of raw string values,
        metadata is a dict of field_name -> string value.
    """
    from forge.config import get_settings

    settings = get_settings()

    tags: list[str] = []
    for field in settings.trace_tag_fields:
        value = resolve_field(field, state)
        if value:
            tags.append(value)

    metadata: dict[str, Any] = {}
    for field in settings.trace_metadata_fields:
        value = resolve_field(field, state)
        if value is not None:
            metadata[field.value] = value

    return tags, metadata
