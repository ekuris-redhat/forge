# Proposal: Stable PR-to-Ticket Association via State Lookup

**Author:** eshulman2
**Date:** 2026-04-20
**Status:** Draft
**Type:** Tech Debt

## Summary

GitHub webhook events for PR comments and CI checks are currently associated with a Jira ticket by extracting the ticket key from the PR title using a regex (`[A-Z]+-\d+`). This is fragile: if the title is edited, the title format changes, or the regex doesn't match, the event is silently dropped with `no_ticket_association`. A more reliable approach is to look up the workflow checkpoint by PR number, using data Forge itself wrote.

## Motivation

### Problem Statement

When GitHub sends a `check_run` or `issue_comment` event, `parse_github_webhook` extracts the ticket key like this:

```python
pr_title = pr.get("title", "")
ticket_key = _extract_ticket_key(pr_title)  # regex on PR title
```

This breaks if:
- A human edits the PR title (removing or changing the `[AISOS-XXX]` prefix)
- The title was never in the expected format (e.g. a PR opened manually against a Forge branch)
- The regex produces a false match from unrelated text in the title
- GitHub truncates long titles

The consequence is silent event drops — the webhook is discarded with `no_ticket_association` and the workflow never resumes. For the CI gate skip feature specifically, a user's `/forge skip-gate` comment would be silently ignored if the PR title was edited after creation.

### Why the Current Approach Exists

The PR title approach was chosen because it requires no additional data store lookup — the ticket key is available directly in the webhook payload. It works reliably for Forge-created PRs where the title follows the `[TICKET-NNN] ...` convention.

### Current Workarounds

None — events that fail title extraction are silently dropped. The only indication is a `no_ticket_association` response from the webhook endpoint.

## Proposal

### Overview

Add a secondary association mechanism: when title extraction fails, look up the workflow checkpoint by PR number or branch name. Forge writes the PR number (`current_pr_number`) and branch name (`branch_name` in context) into the workflow state when it creates a PR. These can be used as a stable reverse-lookup key.

### Detailed Design

#### Option A: In-memory fallback at the webhook layer (preferred)

After `ticket_key = _extract_ticket_key(pr_title)` fails, search active workflow checkpoints for one that contains the PR number:

```python
if not ticket_key:
    ticket_key = await _find_ticket_by_pr_number(pr_number, repo_full_name)
```

`_find_ticket_by_pr_number` scans the Redis checkpoint index for a workflow whose state has `current_pr_number == pr_number` and whose `current_repo` matches `repo_full_name`. This is the same mechanism used by `_find_workflow_by_state` in the worker.

This keeps the webhook handler stateless for the common case (title extraction succeeds) and only falls back to a Redis scan when needed.

#### Option B: PR-number-to-ticket index in Redis

When Forge creates a PR, write a lightweight index entry: `pr:{repo}:{pr_number} → ticket_key`. Look this up directly in the webhook handler. No checkpoint scan needed.

```python
# In create_pull_request node, after PR is created:
await redis.set(f"pr:{current_repo}:{pr_number}", ticket_key, ex=90*24*3600)

# In webhook handler:
ticket_key = await redis.get(f"pr:{current_repo}:{pr_number}")
```

This is O(1) lookup but requires a write at PR creation time and managing TTL.

#### Option C: Use branch name instead of PR number

Branch names like `forge/aisos-358` are embedded in `check_run` and `pull_request` payloads and contain the ticket key. This is more reliable than the PR title and already used as a fallback in some webhook handlers.

```python
branch_name = pr.get("head", {}).get("ref", "")
ticket_key = _extract_ticket_key(branch_name) or _extract_ticket_key(pr_title)
```

This is the simplest fix and works for all Forge-created PRs without any Redis changes. It fails only if the branch was renamed (which Forge never does).

### Recommendation

**Implement Option C immediately** (branch name fallback) as a one-line fix with zero risk. It handles 100% of Forge-created PRs.

**Implement Option B** as a follow-up for robustness — the Redis index is the authoritative source and survives any title or branch name changes.

Option A (checkpoint scan) is too expensive to run on every webhook — checkpoint scans are O(n workflows) and add latency to the webhook acknowledgment path.

### Affected Webhook Events

All GitHub webhook events currently use title-based extraction:
- `pull_request` — uses PR title then branch name (already has fallback)
- `check_run` — uses branch name from associated PRs (already reasonably stable)
- `pull_request_review` — uses PR title then branch name
- `issue_comment` — uses PR title only ← **most fragile, no fallback**

The `issue_comment` handler is the highest priority since it's the new path used by `/forge skip-gate`.

## Implementation Plan

### Phase 1 — Branch name fallback for `issue_comment` (1 hour)

In `parse_github_webhook`, for `issue_comment` events, also try to extract the ticket key from the branch ref:

```python
elif event_type == "issue_comment":
    issue = payload.get("issue", {})
    if "pull_request" in issue:
        pr_number = issue.get("number")
        pr_title = issue.get("title", "")
        # Try title first, fall back to branch if available in payload
        ticket_key = _extract_ticket_key(pr_title)
        # Note: issue_comment payload doesn't include branch ref directly;
        # need to use PR number to fetch it or rely on title only for now.
```

Note: GitHub's `issue_comment` payload does not include the branch ref, only the issue number and title. Option B (Redis index) is the correct long-term fix for `issue_comment`.

### Phase 2 — Redis PR-number index (half day)

- Write `pr:{repo}:{pr_number} → ticket_key` in `create_pull_request` node
- Read it in webhook handler when title extraction fails
- Set TTL to 90 days

### Dependencies

- [ ] Redis client available in webhook handler (currently only used in the queue producer/consumer)
- [ ] Decide whether the Redis index write belongs in `create_pull_request` or in a post-PR-creation hook

## Open Questions

- [ ] Should the PR-number index be written for bug workflow PRs as well as feature workflow PRs?
- [ ] If a PR is retried (new branch, same ticket), does the old index entry cause issues?
- [ ] Should the webhook handler log a warning when it falls back to state lookup, to make the fragility visible in monitoring?
