"""Utility for retrieving active revision context from workflow state and Jira."""

import asyncio
import contextlib
import json
import logging
import re
from typing import Any

from forge.integrations.agents import ForgeAgent
from forge.integrations.jira.client import JiraClient
from forge.prompts import load_prompt
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


async def generate_revision_delta(
    state: FeatureState,
    ticket_data: list[dict[str, Any]],
    feedback: str,
    agent: ForgeAgent,
) -> dict[str, Any]:
    """Generate delta-revision instruction set using the LLM.

    Args:
        state: Current FeatureState.
        ticket_data: Structured details of existing active tickets.
        feedback: Product Owner or Developer feedback.
        agent: ForgeAgent client to invoke the LLM.

    Returns:
        A dictionary containing to_create, to_edit, and to_archive lists.
    """
    ticket_key = state.get("ticket_key", "")

    # Serialize existing tickets to a JSON string or clear list for the prompt
    serialized_tickets = json.dumps(ticket_data, indent=2)

    # Load prompt template
    prompt = load_prompt(
        "generate-revision-delta",
        ticket_data=serialized_tickets,
        feedback=feedback,
    )

    # Invoke the agent for raw completion using run_task
    logger.info("Invoking ForgeAgent for delta-revision orchestration.")
    response_text = await agent.run_task(
        task="generate-revision-delta",
        prompt=prompt,
        context={"ticket_key": ticket_key},
    )

    # Parse and validate conforming JSON delta structure
    try:
        # Robustly extract JSON from potential markdown/code block wrapper
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        # Find first '{' and last '}'
        match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1)

        delta = json.loads(cleaned)
    except Exception as e:
        logger.error(f"Failed to parse delta-revision JSON from agent response: {e}")
        logger.debug(f"Raw response was: {response_text}")
        # Return an empty delta structure on parsing failure
        return {"to_create": [], "to_edit": [], "to_archive": []}

    # Ensure all required keys exist and are lists
    if not isinstance(delta, dict):
        delta = {}

    for key in ("to_create", "to_edit", "to_archive"):
        if key not in delta or not isinstance(delta[key], list):
            delta[key] = []

    return delta


def validate_delta_response(delta: dict[str, Any], existing_keys: list[str]) -> dict[str, Any]:
    """Validate and filter the LLM delta-revision response structure.

    Args:
        delta: The raw parsed delta dictionary containing to_create, to_edit, to_archive.
        existing_keys: The list of active issue keys prior to the delta revision.

    Returns:
        A validated delta dictionary where edits and archives are strictly limited
        to existing active keys, and structure is normalized.
    """
    validated = {
        "to_create": [],
        "to_edit": [],
        "to_archive": []
    }

    # Ensure to_create has elements with valid fields
    for item in delta.get("to_create", []):
        if isinstance(item, dict) and "summary" in item and "description" in item:
            validated["to_create"].append({
                "summary": str(item["summary"]),
                "description": str(item["description"]),
                "repo": str(item.get("repo", ""))
            })

    # Ensure to_edit has elements with valid fields, and only references existing keys
    existing_set = set(existing_keys)
    for item in delta.get("to_edit", []):
        if isinstance(item, dict) and "key" in item and "summary" in item and "description" in item:
            key = str(item["key"])
            if key in existing_set:
                validated["to_edit"].append({
                    "key": key,
                    "summary": str(item["summary"]),
                    "description": str(item["description"]),
                    "repo": str(item.get("repo", ""))
                })
            else:
                logger.warning(f"validate_delta_response: Ignoring edit request for non-existent key {key}")

    # Ensure to_archive only references existing keys
    for item in delta.get("to_archive", []):
        if isinstance(item, dict) and "key" in item:
            key = str(item["key"])
            if key in existing_set:
                validated["to_archive"].append({
                    "key": key
                })
            else:
                logger.warning(f"validate_delta_response: Ignoring archive request for non-existent key {key}")

    return validated


