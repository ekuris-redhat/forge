# Proposal: PR Description Sync After CI Fix Commits

**Author:** eshulman2
**Date:** 2026-04-20
**Status:** Implemented

## Summary

When Forge applies autonomous CI fixes, the code changes it makes may alter behaviour described in the PR. The PR description is never updated to reflect these changes, leaving reviewers with an inaccurate picture of what the PR actually does. This proposal adds a lightweight agent pass after each successful CI fix push that reads the fix diff and the current PR description, and updates the description if the changes warrant it.

## Motivation

### Problem Statement

CI fix commits are written to make checks pass, not to preserve correctness of documentation. When a fix changes something semantically meaningful — like adjusting a timing constant, changing algorithm parameters, or modifying expected values — the PR description is left describing the original intent, not what the code now does.

Real example from this project: the `shouldReconcile` jitter fix changed the effective timing window from ±10% to ±20%. The PR description still says ±10%. A reviewer relying on the description to understand the change would reach an incorrect conclusion.

### Current Workarounds

Reviewers must manually diff the CI fix commits against the PR description and note discrepancies. This is error-prone and relies on the reviewer noticing that a CI fix changed something semantically meaningful rather than just fixing a lint error.

## Proposal

### Overview

After each successful CI fix push, run a short agent task that reads the fix diff and the current PR description, reasons about whether the diff changes any facts stated in the description, and if so rewrites the relevant sections. A Jira comment notes that the description was updated.

This runs only when CI fixes produce actual code changes (not format-only fixes). It is lightweight — a single LLM call with the diff and description as context, no tools needed.

### Detailed Design

#### When it runs

After the CI fix commits are pushed in `attempt_ci_fix`, before returning to `wait_for_ci_gate`. Specifically, after the `if unpushed:` push block in `ci_evaluator.py` confirms commits were pushed.

Only runs when the fix commit diff is non-trivial (i.e. contains substantive changes — skip if the diff only touches whitespace, comments, or auto-generated files).

#### What the agent does

1. Read `git diff origin/main..HEAD` to see all changes on the branch, including the CI fix commits
2. Read the current PR description from GitHub
3. Reason: do any facts in the description conflict with what the diff shows?
   - Changed constants or thresholds (e.g. ±10% → ±20%)
   - Changed behaviour or algorithm  
   - New or removed features visible in the diff
   - Test assertions that no longer reflect the implementation
4. If conflicts found: rewrite only the affected sentences/paragraphs. Leave the rest unchanged.
5. If no conflicts: skip silently — no update, no comment.

#### Implementation

**New node (or inline in `attempt_ci_fix`):** After the push block:

```python
if unpushed:
    git.push_to_fork(force=False)
    logger.info(f"CI fix pushed for {ticket_key} (attempt {attempt})")

    # Sync PR description if the fix changed anything semantically meaningful
    await _sync_pr_description_if_needed(state, git, github, jira, pr_number)
```

**`_sync_pr_description_if_needed`:**

```python
async def _sync_pr_description_if_needed(state, git, github, jira, pr_number):
    diff = git._run_git("diff", "origin/main..HEAD", "--stat", check=False).stdout
    if _is_trivial_diff(diff):
        return

    full_diff = git._run_git("diff", "origin/main..HEAD", check=False).stdout[:8000]
    pr_data = await github.get_pull_request(owner, repo, pr_number)
    current_body = pr_data.get("body", "")

    prompt = load_prompt(
        "sync-pr-description",
        diff=full_diff,
        current_description=current_body,
    )
    agent = ForgeAgent(settings)
    updated_body = await agent.run_task(
        task="sync-pr-description",
        prompt=prompt,
        include_tools=False,
    )

    if updated_body and updated_body.strip() != current_body.strip():
        await github.update_pull_request(owner, repo, pr_number, body=updated_body)
        await jira.add_comment(
            ticket_key,
            f"PR description updated to reflect CI fix changes (attempt {attempt})."
        )
```

**New prompt `src/forge/prompts/v1/sync-pr-description.md`:**

```
You are reviewing a pull request description against the actual code changes on the branch.

## Current PR Description
{current_description}

## Code Diff (branch vs main)
{diff}

Your task:
1. Identify any facts in the PR description that are contradicted or made inaccurate by the diff.
2. Rewrite only the affected sentences or paragraphs to match what the code actually does.
3. Do not add new sections. Do not remove existing sections unless they describe something completely removed.
4. If the description is accurate as written, return it unchanged.
5. Return the full updated description — not a diff, not a summary.

Focus on: changed constants, thresholds, percentages, algorithm behaviour, expected outcomes, and test assertions.
Ignore: formatting fixes, import reordering, auto-generated file changes.
```

**`_is_trivial_diff` helper:** Returns True if the diff only touches files matching `*.pb.go`, `zz_generated.*`, formatting-only changes (gofmt, ruff), or the changed line count is below a threshold (e.g. 5 lines).

#### New GitHub client method

```python
async def update_pull_request(
    self, owner: str, repo: str, pr_number: int, body: str
) -> dict:
    """Update the body of an existing pull request."""
```

Uses `PATCH /repos/{owner}/{repo}/pulls/{pr_number}`.

### User Experience

```
# CI fix changes jitter constant from ±10% to ±20% to fix a test assertion.
# Forge pushes the fix commit, then runs the description sync:

[PR #759 body, before]
"The reconciler schedules a requeue with ±10% jitter on the resync period."

[PR #759 body, after]
"The reconciler schedules a requeue with ±20% jitter on the resync period,
ensuring early-firing requeues are always followed by a new requeue for
the remaining time."

[Jira comment on AISOS-376]
PR description updated to reflect CI fix changes (attempt 2).
```

## Alternatives Considered

| Alternative | Pros | Cons | Why Not |
|-------------|------|------|---------|
| Always regenerate PR description after every CI fix | Fresh, complete | Expensive; loses custom edits by human reviewers | Overkill — most CI fixes are trivial |
| Only update on human request | No accidental changes | Same problem as today — reviewers must notice | Defeats the purpose |
| Add a note at the bottom listing CI fix commits | Simple | Doesn't fix the inaccurate description; reviewers still have to reconcile manually | Doesn't solve the problem |
| Run as part of AI code review (local_review) | Reuses existing node | local_review runs before PR creation, not after CI fixes | Wrong timing |

## Implementation Plan

### Phases

1. **Phase 1:** `_sync_pr_description_if_needed` helper + `sync-pr-description` prompt + `update_pull_request` GitHub client method. (~3 hours)
2. **Phase 2:** Wire into `attempt_ci_fix` after push. (~1 hour)
3. **Phase 3:** `_is_trivial_diff` heuristic to skip format-only changes. (~1 hour)
4. **Phase 4:** Unit tests for trivial diff detection and prompt correctness. (~half day)

### Dependencies

- [ ] `GitHubClient.update_pull_request` method (PATCH endpoint, already has auth)
- [ ] `sync-pr-description` prompt template

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Agent incorrectly rewrites a section that was accurate | Low | Med | Prompt is conservative — only rewrite contradicted facts; reviewer sees the update in the PR timeline |
| Large diffs exceed context window | Low | Low | Diff is truncated to 8000 chars; `--stat` pre-filter catches trivial changes |
| GitHub rate limit from PR update on every fix attempt | Low | Low | Only runs when diff is non-trivial and description actually changes |

## Open Questions

- [ ] Should the updated description include a footer note like `*(description updated by Forge after CI fix — attempt 2)*` for traceability in the PR timeline?
- [ ] Should this also run after the initial PR creation to catch cases where the agent-generated body was already inaccurate from the start?
