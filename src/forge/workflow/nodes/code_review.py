"""Shared code review utilities used across workflow nodes.

Provides two reusable operations:
  - run_post_change_review: runs the local-review container skill after any
    code-changing step, commits fixes in-place
  - sync_pr_description: updates the PR body if commit messages contradict it
"""

import logging
import time
from pathlib import Path
from typing import Any

from forge.config import get_settings
from forge.integrations.agents import ForgeAgent
from forge.integrations.github.client import GitHubClient
from forge.integrations.jira.client import JiraClient
from forge.prompts import load_prompt
from forge.sandbox import ContainerRunner
from forge.workflow.stats import STAGE_REVIEW
from forge.workflow.stats_utils import record_stage_end, record_stage_start, record_tokens
from forge.workspace.git_ops import GitOperations
from forge.workspace.manager import Workspace

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    """Estimate token count from text length (approx. 4 chars per token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


async def run_post_change_review(
    workspace_path: str,
    ticket_key: str,
    current_repo: str,
    branch_name: str,
    spec_content: str = "",
    guardrails: str = "",
    label: str = "post-change",
    state: Any = None,
) -> bool:
    """Run the local-review container skill after a code-changing step.

    Mirrors what local_reviewer.py does: runs the review in a container,
    commits any in-place fixes it makes. Non-blocking — failures are logged
    and the caller proceeds regardless.

    Args:
        workspace_path: Absolute path to the git workspace.
        ticket_key: Jira ticket key (for commit messages and logging).
        current_repo: Full repo name (owner/repo).
        branch_name: Current branch name.
        spec_content: Spec to guide the review (optional).
        guardrails: Repository guidelines (optional).
        label: Short label for log messages (e.g. "ci-fix", "post-change").
        state: Optional workflow state.

    Returns:
        True if the review committed any fixes, False otherwise.
    """
    settings = get_settings()
    node_start = None
    if state is not None:
        start_updates = record_stage_start(state, STAGE_REVIEW, model_name=settings.llm_model)
        state.setdefault("stage_timestamps", {}).update(start_updates.get("stage_timestamps", {}))
        node_start = time.monotonic()

    try:
        task_description = load_prompt(
            "local-review",
            workspace_path=workspace_path,
            spec_content=spec_content[:3000] if spec_content else "Not available",
            guardrails=guardrails[:2000] if guardrails else "",
        )

        runner = ContainerRunner(settings)
        result = await runner.run(
            workspace_path=Path(workspace_path),
            task_summary=f"Post-{label} code review",
            task_description=task_description,
            ticket_key=ticket_key,
            task_key=f"{ticket_key}-review-{label}",
            repo_name=current_repo,
        )

        if state is not None:
            input_tokens = _estimate_tokens(task_description)
            output_tokens = _estimate_tokens(result.stdout) if result.stdout else 0
            token_updates = record_tokens(state, STAGE_REVIEW, input_tokens, output_tokens)
            state.setdefault("stage_timestamps", {}).update(
                token_updates.get("stage_timestamps", {})
            )
            state.setdefault("stage_token_usage", {}).update(
                token_updates.get("stage_token_usage", {})
            )
            state.setdefault("token_usage", {}).update(token_updates.get("token_usage", {}))

        git = GitOperations(
            Workspace(
                path=Path(workspace_path),
                repo_name=current_repo,
                branch_name=branch_name,
                ticket_key=ticket_key,
            )
        )

        committed = False
        if git.has_uncommitted_changes():
            git.stage_all()
            git.commit(f"[{ticket_key}] fix: address issues found in {label} review")
            logger.info(f"Committed {label} review fixes for {ticket_key}")
            committed = True
        else:
            logger.info(f"Post-{label} review: no fixes needed for {ticket_key}")

        if state is not None and node_start is not None:
            machine_time = time.monotonic() - node_start
            end_updates = record_stage_end(state, STAGE_REVIEW, machine_time)
            state.setdefault("stage_timestamps", {}).update(end_updates.get("stage_timestamps", {}))

        return committed

    except Exception as e:
        logger.warning(f"Post-{label} review failed (non-fatal): {e}")
        if state is not None and node_start is not None:
            machine_time = time.monotonic() - node_start
            end_updates = record_stage_end(state, STAGE_REVIEW, machine_time)
            state.setdefault("stage_timestamps", {}).update(end_updates.get("stage_timestamps", {}))
        return False


async def sync_pr_description(
    state: Any,
    git: Any,
    owner: str,
    repo: str,
    pr_number: int | None,
    attempt: int,
) -> None:
    """Update the PR description if commit messages contradict any stated facts.

    Uses commit messages (not raw diff) as the source of truth — they are
    already a curated summary of what changed. Errors are swallowed so this
    never blocks any workflow step.

    Args:
        state: Current workflow state (for ticket_key and audit comment).
        git: GitOperations instance for the workspace.
        owner: Repository owner.
        repo: Repository name.
        pr_number: Pull request number, or None to skip.
        attempt: Which code-change attempt this follows (0 = initial PR creation).
    """
    if pr_number is None:
        return

    settings = get_settings()
    start_updates = record_stage_start(state, STAGE_REVIEW, model_name=settings.llm_model)
    state.setdefault("stage_timestamps", {}).update(start_updates.get("stage_timestamps", {}))
    node_start = time.monotonic()

    try:
        commit_log = git._run_git(
            "log",
            "origin/main..HEAD",
            "--pretty=format:%s%n%b",
            "--no-merges",
            check=False,
        ).stdout.strip()

        if not commit_log:
            logger.debug("PR description sync skipped — no commits on branch")
            machine_time = time.monotonic() - node_start
            end_updates = record_stage_end(state, STAGE_REVIEW, machine_time)
            state.setdefault("stage_timestamps", {}).update(end_updates.get("stage_timestamps", {}))
            return

        github = GitHubClient()
        jira = JiraClient()
        try:
            pr_data = await github.get_pull_request(owner, repo, pr_number)
            current_body = pr_data.get("body", "") or ""

            prompt = load_prompt(
                "sync-pr-description",
                current_description=current_body,
                commit_log=commit_log,
            )
            agent = ForgeAgent(settings)
            try:
                updated_body = await agent.run_task(
                    task="sync-pr-description",
                    prompt=prompt,
                    context={"owner": owner, "repo": repo, "pr_number": pr_number},
                    trace_context={
                        "ticket_key": state.get("ticket_key", ""),
                        "ticket_type": state.get("ticket_type", ""),
                        "current_node": state.get("current_node", ""),
                        "ci_status": state.get("ci_status", ""),
                        "event_type": state.get("event_type", ""),
                        "event_source": state.get("context", {}).get("source", ""),
                        "retry_count": state.get("retry_count", 0),
                    },
                    include_tools=False,
                )
            finally:
                await agent.close()

            input_tokens = _estimate_tokens(prompt)
            output_tokens = _estimate_tokens(updated_body) if updated_body else 0
            token_updates = record_tokens(state, STAGE_REVIEW, input_tokens, output_tokens)
            state.setdefault("stage_timestamps", {}).update(
                token_updates.get("stage_timestamps", {})
            )
            state.setdefault("stage_token_usage", {}).update(
                token_updates.get("stage_token_usage", {})
            )
            state.setdefault("token_usage", {}).update(token_updates.get("token_usage", {}))

            if updated_body:
                updated_body = agent._strip_preamble(updated_body)
            if updated_body and updated_body.strip() != current_body.strip():
                await github.update_pull_request(owner, repo, pr_number, body=updated_body)
                ticket_key = state.get("ticket_key", "")
                label = f"CI fix attempt {attempt}" if attempt > 0 else "PR creation"
                await jira.add_comment(
                    ticket_key,
                    f"PR description updated to reflect changes ({label}).",
                )
                logger.info(f"PR #{pr_number} description synced after {label}")
            else:
                logger.debug(f"PR #{pr_number} description already accurate — no update needed")
        finally:
            await github.close()
            await jira.close()

        machine_time = time.monotonic() - node_start
        end_updates = record_stage_end(state, STAGE_REVIEW, machine_time)
        state.setdefault("stage_timestamps", {}).update(end_updates.get("stage_timestamps", {}))

    except Exception as e:
        logger.warning(f"PR description sync failed (non-fatal): {e}")
        machine_time = time.monotonic() - node_start
        end_updates = record_stage_end(state, STAGE_REVIEW, machine_time)
        state.setdefault("stage_timestamps", {}).update(end_updates.get("stage_timestamps", {}))
