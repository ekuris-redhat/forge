"""Pydantic models and validation logic for LLM delta update responses."""

import logging
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from forge.config import get_settings
from forge.integrations.jira.client import JiraClient, MissingProjectConfig
from forge.models.workflow import ForgeLabel

logger = logging.getLogger(__name__)


class EditTicket(BaseModel):
    """Pydantic model representing an item in the to_edit list of a delta response."""

    model_config = ConfigDict(extra="forbid")

    key: str
    summary: str
    description: str
    repo: str | None = None


class CreateTicket(BaseModel):
    """Pydantic model representing an item in the to_create list of a delta response."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    description: str
    repo: str | None = None
    parent_epic_key: str | None = None


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


async def apply_delta_updates(
    jira: JiraClient,
    delta: LLMDeltaResponse,
    state: dict[str, Any],
    level: str,
    project_key: str,
) -> dict[str, Any]:
    """Sequentially apply delta updates to Jira and update workflow state on success.

    Ensures transactional safety: if any Jira operation fails with an exception,
    the workflow state is left completely untouched and the exception is propagated.

    Args:
        jira: JiraClient instance.
        delta: Validated LLMDeltaResponse containing actions to apply.
        state: Current workflow state.
        level: Node level ("epic" or "task").
        project_key: Key of the project under which issues are updated/created.

    Returns:
        dict[str, Any]: The updated workflow state if successful.
    """
    if level not in ("epic", "task"):
        raise ValueError(f"Unsupported level: {level}")

    # Prepare temporary state trackers
    epic_keys = list(state.get("epic_keys") or [])
    task_keys = list(state.get("task_keys") or [])
    tasks_by_repo = {
        repo: list(keys)
        for repo, keys in (state.get("tasks_by_repo") or {}).items()
    }

    # Fetch parent mappings for tasks to assist with task creation context if needed
    task_to_parent = {}
    if level == "task" and task_keys:
        async def _get_parent_key(tk: str) -> str | None:
            try:
                issue = await jira.get_issue(tk)
                return issue.parent_key if issue else None
            except Exception:
                return None

        import asyncio
        parent_keys = await asyncio.gather(*(_get_parent_key(tk) for tk in task_keys))
        task_to_parent = {tk: pk for tk, pk in zip(task_keys, parent_keys) if pk}

    # 1. Archive keys in to_archive
    for key in delta.to_archive:
        await jira.archive_issue(key, archive_subtasks=(level == "epic"))
        if level == "epic":
            if key in epic_keys:
                epic_keys.remove(key)
        elif level == "task":
            if key in task_keys:
                task_keys.remove(key)
            for repo, keys in list(tasks_by_repo.items()):
                if key in keys:
                    keys.remove(key)
                if not keys:
                    tasks_by_repo.pop(repo, None)

    # 2. Edit keys in to_edit
    for item in delta.to_edit:
        await jira.update_summary_and_description(item.key, item.summary, item.description)
        repo = getattr(item, "repo", None) or ""
        if repo and "/" in repo:
            current_labels = await jira.get_labels(item.key)
            repo_labels_to_remove = [l for l in current_labels if l.startswith("repo:")]
            if repo_labels_to_remove:
                await jira.remove_labels(item.key, repo_labels_to_remove)
            await jira.add_labels(item.key, [f"repo:{repo}"])

            if level == "task":
                for old_repo, keys in list(tasks_by_repo.items()):
                    if item.key in keys:
                        keys.remove(item.key)
                    if not keys:
                        tasks_by_repo.pop(old_repo, None)
                tasks_by_repo.setdefault(repo, []).append(item.key)

    # 3. Create items in to_create
    ticket_key = state.get("ticket_key", "")
    for item in delta.to_create:
        summary = item.summary
        description = item.description
        repo = item.repo or ""

        if level == "epic":
            labels = [
                ForgeLabel.FORGE_MANAGED.value,
                f"forge:parent:{ticket_key}",
            ]
            if repo and "/" in repo:
                labels.append(f"repo:{repo}")

            new_key = await jira.create_epic(
                project_key=project_key,
                summary=summary,
                description=description,
                parent_key=ticket_key,
                labels=labels,
            )
            epic_keys.append(new_key)

        elif level == "task":
            parent_epic_key = getattr(item, "parent_epic_key", None)

            # Search in summary/description if not found
            if not parent_epic_key and epic_keys:
                for ek in epic_keys:
                    if ek in summary or ek in description:
                        parent_epic_key = ek
                        break

            # Search by active tasks in same repo
            if not parent_epic_key and repo and repo != "unknown" and epic_keys:
                for tk, pk in task_to_parent.items():
                    try:
                        task_labels = await jira.get_labels(tk)
                        task_repo = "unknown"
                        for label in task_labels:
                            if label.startswith("repo:"):
                                task_repo = label[5:]
                                break
                        if task_repo == repo:
                            parent_epic_key = pk
                            break
                    except Exception:
                        pass

            # Fallback to first epic key
            if not parent_epic_key and epic_keys:
                parent_epic_key = epic_keys[0]

            if not parent_epic_key:
                raise ValueError(
                    f"Transaction failure: No parent Epic key found for new Task '{summary}'"
                )

            # Determine task repo
            if not repo or repo == "unknown" or "/" not in repo:
                try:
                    epic_labels = await jira.get_labels(parent_epic_key)
                    for label in epic_labels:
                        if label.startswith("repo:"):
                            repo = label[5:]
                            break
                except Exception:
                    repo = "unknown"

            if not repo or repo == "unknown" or "/" not in repo:
                try:
                    repo = await jira.get_project_default_repo(project_key)
                except MissingProjectConfig:
                    settings = get_settings()
                    repo = (
                        settings.github_default_repo
                        if not settings.forge_require_project_config
                        else ""
                    )

            if not repo or "/" not in repo:
                repo = "unknown"

            labels = [
                ForgeLabel.FORGE_MANAGED.value,
                f"forge:parent:{ticket_key}",
            ]
            if repo and repo != "unknown":
                labels.append(f"repo:{repo}")

            new_key = await jira.create_task(
                project_key=project_key,
                summary=summary,
                description=description,
                parent_key=parent_epic_key,
                labels=labels,
            )
            task_keys.append(new_key)
            tasks_by_repo.setdefault(repo, []).append(new_key)

    # 4. Success: Apply all state trackers to a copy of state and return it
    updated_state = dict(state)
    if level == "epic":
        updated_state["epic_keys"] = epic_keys
    elif level == "task":
        updated_state["task_keys"] = task_keys
        updated_state["tasks_by_repo"] = tasks_by_repo

    return updated_state
