"""Utility for retrieving active revision context from workflow state and Jira."""

import asyncio
import contextlib
import logging
from typing import Any

from forge.integrations.jira.client import JiraClient
from forge.workflow.feature.state import FeatureState

logger = logging.getLogger(__name__)


async def get_current_revision_state(
    state: FeatureState,
    level: str,
    jira: JiraClient,
) -> list[dict[str, Any]]:
    """Retrieve active revision context (summary and description) for the specified level.

    Args:
        state: Current workflow state.
        level: Level of tickets to retrieve ("epic" or "task").
        jira: Jira client used to query issue details.

    Returns:
        A list of dictionaries with key, summary, and description.

    Raises:
        ValueError: If an unsupported level is specified.
    """
    if level not in ("epic", "task"):
        raise ValueError(f"Unsupported level: {level}")

    keys: list[str] = []

    if level == "epic":
        with contextlib.suppress(KeyError, TypeError):
            epic_keys = state["epic_keys"]
            if isinstance(epic_keys, list):
                keys = [str(k) for k in epic_keys if k]
    elif level == "task":
        # Extract from task_keys or values of tasks_by_repo
        task_keys = None
        with contextlib.suppress(KeyError, TypeError):
            task_keys = state["task_keys"]

        if task_keys and isinstance(task_keys, list):
            keys = [str(k) for k in task_keys if k]
        else:
            with contextlib.suppress(KeyError, TypeError):
                tasks_by_repo = state["tasks_by_repo"]
                if isinstance(tasks_by_repo, dict):
                    repo_keys: list[str] = []
                    for val in tasks_by_repo.values():
                        if isinstance(val, list):
                            repo_keys.extend(val)
                    keys = [str(k) for k in repo_keys if k]

    # Deduplicate while preserving insertion order
    seen = set()
    deduped_keys = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            deduped_keys.append(k)

    if not deduped_keys:
        return []

    async def _fetch_issue_state(key: str) -> dict[str, Any] | None:
        try:
            issue = await jira.get_issue(key)
            if issue is None:
                return None

            summary = ""
            with contextlib.suppress(AttributeError, TypeError):
                if issue.summary is not None:
                    summary = str(issue.summary)

            description = ""
            with contextlib.suppress(AttributeError, TypeError):
                if issue.description is not None:
                    description = str(issue.description)

            return {
                "key": key,
                "summary": summary,
                "description": description,
            }
        except Exception as e:
            logger.warning(f"Error fetching issue {key} from Jira: {e}")
            return None

    # Fetch concurrently using asyncio.gather
    results = await asyncio.gather(*[_fetch_issue_state(k) for k in deduped_keys])

    # Filter out None values in case of fetch failures
    return [res for res in results if res is not None]
