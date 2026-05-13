# Proposal: Dedicated implement_review Node for PR Review Feedback

**Author:** eshulman2
**Date:** 2026-04-20
**Status:** Implemented

## Summary

When a human reviewer requests changes on a PR, the workflow currently routes back to `implement_task` — a node designed to implement Jira tasks from scratch. This is the wrong tool: it gives the container a confused mix of original task instructions and a tacked-on feedback comment, and then routes through `create_pr` even though the PR already exists. This proposal introduces a dedicated `implement_review` node that addresses reviewer feedback with proper context, pushes to the existing branch, and routes directly back to `wait_for_ci_gate`. It also defines a first-class mechanism for the agent to register a reasoned disagreement with a review comment rather than silently complying or silently ignoring it.

## Motivation

### Problem Statement

The current feedback loop when a PR reviewer requests changes:

```
human_review_gate (changes_requested)
    → implement_task          ← wrong node: built for "implement from spec"
        → local_review
        → create_pr           ← tries to open a second PR on an existing branch
        → teardown → wait_for_ci_gate
```

Three concrete problems:

1. **Wrong input contract.** `implement_task` receives the Jira task description as its primary instruction and the review comment as a secondary `feedback_comment` field. The container agent sees "build the auth system" plus "the reviewer says the session token should be signed" — a confusing mix of original scope and targeted feedback that doesn't clearly tell the agent what to do.

2. **Broken PR flow.** After `implement_task`, the flow passes through `create_pr`, which tries to open a new pull request. But the branch already has an open PR. This either fails, creates a duplicate PR, or produces confusing state.

3. **No mechanism for disagreement.** If a reviewer requests a change that the agent believes is technically incorrect, unnecessary, or contradicts the spec, the agent has no way to express this. It either blindly implements the change or the workflow breaks. Neither outcome is useful — a senior engineer reviewing a PR expects the implementor to flag genuine concerns, not silently comply or silently ignore.

### Current Workarounds

Engineers manually close the Forge PR, make changes by hand, and open a new PR. Or they approve the PR with comments and handle the feedback outside of Forge entirely.

## Proposal

### Overview

Add an `implement_review` node that:
1. Runs in a container with review comments and the current branch diff as its primary context (not the original task description)
2. Classifies each review comment as *actionable* (agent agrees and will implement) or *contested* (agent has a reasoned objection)
3. For contested comments: posts a structured response on the PR explaining the agent's reasoning and pauses at a new `review_response_gate` for human confirmation
4. For actionable comments: implements targeted changes, runs a post-change review, pushes to the existing branch, then routes to `wait_for_ci_gate`

The PR description is synced after the push (reusing `sync_pr_description` from `code_review.py`).

### Detailed Design

#### New graph path (both feature and bug workflows)

```
human_review_gate (changes_requested)
    → implement_review
        ├── actionable comments only  → [implement] → local_review → push → wait_for_ci_gate
        └── contested comments        → review_response_gate [pause]
                                            ├── human confirms → implement_review (now fully actionable)
                                            └── human withdraws → human_review_gate (re-pause, wait for re-review)
```

#### New state fields

```python
class ReviewIntegrationState(TypedDict, total=False):
    # existing
    ai_review_status: str | None
    ai_review_results: list[dict[str, Any]]
    human_review_status: str | None
    pr_merged: bool
    # new
    review_comments: list[dict[str, Any]]   # parsed review comments from webhook
    contested_comments: list[dict[str, Any]] # comments agent disagrees with
    review_response_posted: bool             # whether agent posted its objections
```

#### `implement_review` node

The container receives:
- The full review body (parsed into individual comments if possible)
- The current `git diff origin/main..HEAD` — what the code looks like now
- The original spec (for grounding what was agreed)
- Instruction to classify each comment before acting

Container task prompt (sketch):

```
You are addressing code review feedback on an open pull request.

## Review Comments
{review_comments}

## Current Branch Diff
{current_diff}

## Original Specification
{spec_content}

## Instructions

For each review comment:

1. Classify it:
   - ACTIONABLE: you agree the change is correct and will implement it
   - CONTESTED: you have a reasoned technical objection (the change contradicts
     the spec, introduces a bug, or is factually incorrect)

2. If ALL comments are ACTIONABLE:
   - Implement the changes
   - Write a brief summary of what you changed and why
   - Commit with message: "[TICKET] review: address PR feedback"

3. If ANY comments are CONTESTED:
   - Do NOT implement any changes yet
   - Write a structured response for each contested comment explaining:
     * What the reviewer asked for
     * Why you object (with technical reasoning)
     * What you propose instead, if anything
   - Output ONLY the response text — the orchestrator will post it

Do not implement partial changes when any comment is contested.
Either implement all actionable comments (if none are contested) or
output the disagreement response (if any are contested).
```

#### `review_response_gate` node

A new approval gate that pauses after the agent posts its disagreement response. The human reviewer reads the agent's reasoning and:

- **Confirms the original request** — responds with the original label or a comment like "please implement as requested". The gate resumes, the agent treats all comments as actionable and implements.
- **Withdraws or modifies the request** — posts a revised review or approves the PR. The gate resumes and routes back to `human_review_gate`.

This gate follows the same `is_paused` / webhook-resume pattern as other gates. The human signal is detected the same way as other approval events.

#### Post-implementation flow

Once `implement_review` has made changes and committed:

1. `run_post_change_review` (from `code_review.py`) — same quality gate as CI fix path
2. Push to the existing branch — PR updates automatically, no `create_pr` call
3. `sync_pr_description` — update the PR body if the review changes affected stated facts
4. Route to `wait_for_ci_gate` — CI re-runs on the new commits

#### Resume routing

Add to both `route_by_ticket_type` (feature) and `route_entry` (bug):

```python
elif current_node == "implement_review":
    return "implement_review"
elif current_node == "review_response_gate":
    return "review_response_gate"
```

### User Experience

**Happy path (agent agrees with all feedback):**
```
[Reviewer on GitHub PR]
The session token should be HMAC-signed, not just base64 encoded.

[Forge, moments later]
Addressed review feedback:
- Session token is now HMAC-SHA256 signed using the SECRET_KEY setting.

[CI re-runs, passes, PR ready for re-review]
```

**Contested comment:**
```
[Reviewer on GitHub PR]
Remove the retry logic — it's unnecessary complexity.

[Forge, on the PR]
I want to flag a concern before implementing this:

**Contested: "Remove the retry logic"**

The spec (section FR-007) explicitly requires retry on transient OpenStack
API failures with exponential backoff. Removing this would break the spec
requirement and cause test failures in the e2e resync tests.

Proposal: keep the retry logic as-is, or if you'd like to simplify, I can
reduce the maximum retry count from 5 to 3.

Please confirm whether you'd still like this removed (I'll implement it),
or let me know your preference.

[Forge, on Jira AISOS-376]
Review response posted on PR #759. Waiting for human confirmation before
implementing contested changes.
```

**Human confirms anyway:**
```
[Reviewer]
Yes, please remove it — we'll handle retries at the infrastructure level.

[Forge]
Understood. Implementing as requested.
[implements, pushes, CI re-runs]
```

## Alternatives Considered

| Alternative | Pros | Cons | Why Not |
|-------------|------|------|---------|
| Keep routing to `implement_task` with better prompt | Reuses existing node | Still routes through `create_pr`; mixed input context never clean | The contract mismatch is fundamental |
| Always implement review feedback, never disagree | Simple | Agent silently implements incorrect reviews; reviewer expects pushback on bad suggestions | Undermines the quality of the automated implementation |
| Post disagreements as regular comments without pausing | Less interruption | Human might not notice; agent still doesn't implement; workflow stalls indefinitely | Need an explicit gate to resume the workflow |
| Let agent decide whether to implement or contest per-comment (partial implementation) | Flexible | Partial implementation is confusing — some comments addressed, some not; reviewer can't tell what happened | All-or-nothing within a round is cleaner |
| Separate node for "apply review" vs "contest review" with the router deciding | Clean separation | Double container invocation if agent first classifies then implements | Single container call with classification + action is more efficient |

## Implementation Plan

### Phases

1. **Phase 1:** `implement_review` node — container task, post-push flow (push to existing branch, run post-change review, sync description, route to `wait_for_ci_gate`). No disagreement handling yet. (~half day)
2. **Phase 2:** `review_response_gate` — pause node, webhook detection for confirmation/withdrawal, resume routing. (~half day)
3. **Phase 3:** Disagreement classification in container prompt and orchestrator handling of contested vs actionable response. (~half day)
4. **Phase 4:** Tests and wire into both feature and bug graphs. (~half day)

### Dependencies

- [ ] `run_post_change_review` and `sync_pr_description` from `code_review.py` (already implemented)
- [ ] GitHub client needs a way to read individual review comments (not just the review body) — `GET /repos/{owner}/{repo}/pulls/{pr_number}/comments`
- [ ] Worker `_handle_resume_event` needs to detect the human confirmation signal at `review_response_gate`

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Agent contests too aggressively, blocking every review | Med | High | Prompt must require a high bar for contesting — only spec contradictions or clear technical errors, not style preferences |
| Agent contests then implements anyway on retry | Low | Med | `review_response_gate` clears `contested_comments` before re-invoking, so agent sees "all comments confirmed actionable" |
| Review comment parsing fails (GitHub sends complex diff-level comments) | Med | Low | Fall back to raw review body if individual comment parsing fails |

## Open Questions

- [ ] Should the agent be allowed to implement the actionable subset of comments and contest only the contested ones (partial round), or is all-or-nothing per round the right boundary?
- [ ] How many rounds of implement → review → implement should be allowed before escalating to blocked? Currently there is no cap on the revision loop.
- [ ] Should the agent's disagreement response include a proposed alternative (as shown in the example), or should it only explain the objection and let the human decide?
- [ ] For the bug workflow: is the review feedback loop the same as for features, or does a bug fix have a stricter "the fix must match the RCA" constraint that should be checked first?
