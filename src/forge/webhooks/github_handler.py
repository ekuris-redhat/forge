"""GitHub webhook handler for comment events."""

import logging
from typing import Any

from forge.github.command_parser import is_user_authorized, parse_comment_command
from forge.integrations.github.client import GitHubClient

logger = logging.getLogger(__name__)


async def process_comment_webhook(payload: dict[str, Any], event_type: str) -> dict[str, Any]:
    """Process incoming GitHub issue_comment or pull_request_review_comment events.

    Parses the comment body to identify commands, validates user permissions/collaborator status,
    and posts a descriptive warning comment back to the PR if the user is unauthorized.

    Args:
        payload: The raw JSON webhook payload.
        event_type: The GitHub event type ('issue_comment' or 'pull_request_review_comment').

    Returns:
        A dictionary indicating the outcome, e.g.:
        {"status": "ignored", "reason": "..."}
        {"status": "rejected", "reason": "...", "command": "..."}
        {"status": "authorized", "command": "..."}
    """
    # We only care about comment creation
    action = payload.get("action", "")
    if action != "created":
        return {
            "status": "ignored",
            "reason": f"Ignored event action '{action}'. Only 'created' is supported.",
        }

    comment_data = payload.get("comment", {})
    comment_body = comment_data.get("body", "")

    # Parse comment body for command
    command = parse_comment_command(comment_body)
    if not command:
        return {"status": "ignored", "reason": "No supported command found in comment."}

    # Extract repository and user details
    repo_full_name = payload.get("repository", {}).get("full_name", "")
    username = payload.get("sender", {}).get("login", "")

    if not repo_full_name or not username:
        return {
            "status": "ignored",
            "reason": f"Missing repository ({repo_full_name}) or sender ({username}) in payload.",
        }

    # Verify authorization
    authorized = await is_user_authorized(repo_full_name, username)
    if not authorized:
        # Get PR/issue number
        pr_number = None
        if event_type == "issue_comment":
            pr_number = payload.get("issue", {}).get("number")
        elif event_type == "pull_request_review_comment":
            pr_number = payload.get("pull_request", {}).get("number")

        if pr_number:
            owner, _, repo_name = repo_full_name.partition("/")
            warning_body = (
                f"⚠️ User @{username} is not authorized to execute command: '{command}' "
                "on this repository. Only collaborators with write access can run commands."
            )
            client = GitHubClient()
            try:
                await client.create_issue_comment(owner, repo_name, pr_number, warning_body)
                logger.warning(
                    f"Rejected unauthorized command '{command}' by @{username} "
                    f"and posted warning comment to PR #{pr_number}."
                )
            except Exception as e:
                logger.error(f"Failed to post unauthorized warning comment: {e}")
            finally:
                await client.close()
        else:
            logger.warning(
                f"Rejected unauthorized command '{command}' by @{username} "
                f"but could not determine PR number."
            )

        return {
            "status": "rejected",
            "reason": f"User @{username} is not authorized to execute command: '{command}'.",
            "command": command,
        }

    # User is authorized to execute the command
    logger.info(f"Authorized command '{command}' from @{username} on {repo_full_name}.")
    return {"status": "authorized", "command": command}
