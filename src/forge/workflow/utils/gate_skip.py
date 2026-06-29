"""Utility functions for checking and handling gate skipping."""

import logging
from typing import Any

from forge.integrations.github.client import GitHubClient
from forge.services.gate_skip_service import get_skip_status

logger = logging.getLogger(__name__)


async def is_skip_gate_active(state: dict[str, Any]) -> bool:
    """Check if the gate-skipping is active for any PR associated with the state."""
    # 1. Check current_repo and current_pr_number
    current_repo = state.get("current_repo")
    pr_number = state.get("current_pr_number")
    if current_repo and pr_number:
        repo_full = current_repo
        repo = current_repo.split("/")[-1]
        if await get_skip_status(repo_full, pr_number) or await get_skip_status(repo, pr_number):
            return True

    # 2. Check pr_urls list
    pr_urls = state.get("pr_urls", [])
    for pr_url in pr_urls:
        try:
            parts = pr_url.rstrip("/").split("/")
            owner, repo = parts[-4], parts[-3]
            pr_number_url = int(parts[-1])
            repo_full = f"{owner}/{repo}"
            if await get_skip_status(repo_full, pr_number_url) or await get_skip_status(
                repo, pr_number_url
            ):
                return True
        except Exception:
            continue

    return False


async def post_github_skip_comment(state: dict[str, Any], gate_name: str) -> None:
    """Post a comment to the GitHub PR confirming that a developer skipped the gate."""
    # Determine PR details
    current_repo = state.get("current_repo")
    pr_number = state.get("current_pr_number")

    # We can also check pr_urls
    pr_urls = state.get("pr_urls", [])

    prs_to_comment = []
    if current_repo and pr_number:
        parts = current_repo.split("/")
        owner = parts[0] if len(parts) > 1 else ""
        repo = parts[-1]
        if owner:
            prs_to_comment.append((owner, repo, pr_number))

    for pr_url in pr_urls:
        try:
            parts = pr_url.rstrip("/").split("/")
            owner, repo = parts[-4], parts[-3]
            pr_num = int(parts[-1])
            pair = (owner, repo, pr_num)
            if pair not in prs_to_comment:
                prs_to_comment.append(pair)
        except Exception:
            continue

    if not prs_to_comment:
        logger.warning("No PRs found to post skip-gate comment to.")
        return

    github = GitHubClient()
    try:
        for owner, repo, pr_num in prs_to_comment:
            comment_body = f"⏭️ **Gate Bypassed**: '{gate_name}' was skipped because developer skip-gate settings are active."
            # Check if this comment has already been posted to avoid duplicates
            try:
                existing_comments = await github.get_issue_comments(owner, repo, pr_num)
                already_posted = any(
                    comment_body in (c.get("body") or "") for c in existing_comments
                )
            except Exception as ce:
                logger.warning(f"Failed to check existing comments on PR #{pr_num}: {ce}")
                already_posted = False

            if not already_posted:
                await github.create_issue_comment(owner, repo, pr_num, comment_body)
                logger.info(
                    f"Posted skip-gate comment to {owner}/{repo} PR #{pr_num} for gate '{gate_name}'"
                )
            else:
                logger.info(
                    f"Skip-gate comment already exists on {owner}/{repo} PR #{pr_num} for gate '{gate_name}'"
                )
    except Exception as e:
        logger.warning(f"Failed to post skip-gate comment: {e}")
    finally:
        await github.close()
