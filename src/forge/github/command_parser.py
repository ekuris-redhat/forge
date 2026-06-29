"""Parser and authorization checker for GitHub comment commands."""

import logging

from forge.integrations.github.client import GitHubClient

logger = logging.getLogger(__name__)


def parse_comment_command(comment_body: str) -> str | None:
    """Parse a comment body to extract the command if present.

    Supported commands:
    - /forge skip-gate
    - /forge unskip-gate
    - /forge rebase

    Args:
        comment_body: The text of the comment.

    Returns:
        The matched command ('/forge skip-gate', '/forge unskip-gate', '/forge rebase')
        or None if no supported command is found.
    """
    if not comment_body:
        return None

    # Strip whitespace from the body
    body = comment_body.strip()

    # Check for commands at the start of any line or start of the body
    # Support case-insensitive matching
    for line in body.splitlines():
        line_stripped = line.strip().lower()
        if line_stripped.startswith("/forge skip-gate"):
            return "/forge skip-gate"
        if line_stripped.startswith("/forge unskip-gate"):
            return "/forge unskip-gate"
        if line_stripped.startswith("/forge rebase"):
            return "/forge rebase"

    return None


async def is_user_authorized(repo: str, username: str) -> bool:
    """Check if the commenting user has write permissions or collaborator status on the repository.

    Args:
        repo: Repository full name (owner/repo).
        username: GitHub username.

    Returns:
        True if the user is authorized.
    """
    if not repo or not username:
        return False

    owner, _, repo_name = repo.partition("/")
    if not owner or not repo_name:
        return False

    client = GitHubClient()
    try:
        httpx_client = await client._get_client()
        # Call collaborator permission endpoint
        response = await httpx_client.get(
            f"/repos/{owner}/{repo_name}/collaborators/{username}/permission"
        )
        if response.status_code == 200:
            data = response.json()
            permission = data.get("permission")
            # Permission can be 'admin', 'write', 'maintain', etc.
            # Collaborators can have 'read' or 'none', so we check for 'write', 'admin', 'maintain'
            return permission in ("write", "admin", "maintain")

        # Fallback to direct collaborator check
        response_collab = await httpx_client.get(
            f"/repos/{owner}/{repo_name}/collaborators/{username}"
        )
        return response_collab.status_code == 204
    except Exception as e:
        logger.error(f"Failed to check user authorization: {e}")
        return False
    finally:
        await client.close()
