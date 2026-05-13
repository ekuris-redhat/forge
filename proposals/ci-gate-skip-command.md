# Proposal: CI Gate Skip via GitHub PR Comment

**Author:** eshulman2
**Date:** 2026-04-20
**Status:** Implemented

## Summary

When a CI check fails due to unrelated infrastructure issues (flaky DevStack, cloud quota exhaustion, intermittent networking), Forge exhausts all its fix attempts and blocks the workflow — even though the PR code is correct. This proposal adds a `/forge skip-gate <check-name>` comment command on the GitHub PR that tells the CI evaluator to treat a named check as passing, unblocking the workflow without requiring a code change.

## Motivation

### Problem Statement

Forge's CI evaluator treats every failed check the same way: attempt an autonomous fix up to `ci_fix_max_retries` times, then escalate to blocked. There is no way to say "this check is failing for infrastructure reasons unrelated to this PR — ignore it and proceed."

Real examples from this project:
- OpenStack e2e tests failing because DevStack ran out of quota on the CI runner
- A single environment (`epoxy`) timing out while the other two (`flamingo`, `gazpacho`) pass
- A flaky GitHub Actions runner consistently failing one job regardless of code changes

In all these cases, the right action is "skip this check, proceed to human review." Currently the only options are:
1. Wait for the infrastructure to recover and push a no-op commit to re-trigger CI
2. Manually patch the Redis checkpoint via `scripts/patch_checkpoint.py`
3. Escalate the ticket and merge the PR manually, bypassing Forge

### Current Workarounds

Engineers patch the Redis checkpoint directly via `scripts/patch_checkpoint.py` to clear `ci_failed_checks` and reset `current_node`. This is error-prone, requires direct Redis access, and leaves no audit trail.

## Proposal

### Overview

Add `/forge skip-gate <check-name>` and `/forge unskip-gate <check-name>` as PR comment commands on GitHub. When detected, Forge records the named check in state as skipped and re-evaluates CI treating it as passing. A reply comment is posted on the PR confirming the skip, and an audit comment is posted to the linked Jira ticket.

This is a natural fit: CI gates live in GitHub, so the command to skip a CI gate belongs there too.

### Detailed Design

#### Command syntax (GitHub PR comment)

```
/forge skip-gate Run acceptance tests against OpenStack epoxy
```

Multiple skips:
```
/forge skip-gate Run acceptance tests against OpenStack epoxy
/forge skip-gate Run acceptance tests against OpenStack flamingo
```

To remove a previously set skip:
```
/forge unskip-gate Run acceptance tests against OpenStack epoxy
```

The check name is matched case-insensitively as a substring of the actual GitHub check run name. If no matching failed check is found, Forge replies with the list of current failed check names.

#### Webhook delivery

GitHub's `issue_comment` event fires when a comment is posted on a PR. The Forge GitHub webhook handler already parses `issue_comment` events and extracts the ticket key from the PR title (see `forge/integrations/github/webhooks.py:129-136`). The comment body is available at `payload["comment"]["body"]`.

No new webhook registration or GitHub App permission is required — `issue_comment` events are already delivered.

#### State schema — `CIIntegrationState`

```python
class CIIntegrationState(TypedDict, total=False):
    ci_status: str | None
    ci_failed_checks: list[dict[str, Any]]
    ci_fix_attempts: int
    ci_skipped_checks: list[str]   # NEW: check name substrings to treat as passing
```

Initialized to `[]`. Skips persist in state for the lifetime of the PR — they do not reset between pushes. If a check is infrastructure-flaky it will likely fail again after the next push, so the skip should survive re-triggers.

#### Comment detection — `_handle_resume_event` in `worker.py`

Extend the existing GitHub event handler path to detect skip commands from `issue_comment` payloads:

```python
SKIP_GATE_PREFIX = "/forge skip-gate"
UNSKIP_GATE_PREFIX = "/forge unskip-gate"

comment_body = payload.get("comment", {}).get("body", "").strip()

if comment_body.lower().startswith(SKIP_GATE_PREFIX.lower()):
    check_name = comment_body[len(SKIP_GATE_PREFIX):].strip()
    is_skip_gate = True

if comment_body.lower().startswith(UNSKIP_GATE_PREFIX.lower()):
    check_name = comment_body[len(UNSKIP_GATE_PREFIX):].strip()
    is_unskip_gate = True
```

When `is_skip_gate=True`:
- Append `check_name` to `ci_skipped_checks` (de-duplicate)
- Set `is_paused=False`, `current_node="ci_evaluator"` to trigger re-evaluation

When `is_unskip_gate=True`:
- Remove matching entry from `ci_skipped_checks`
- Set `is_paused=False`, `current_node="ci_evaluator"` to re-evaluate

Skip commands only take effect when `current_node` is `wait_for_ci_gate`, `ci_evaluator`, or `attempt_ci_fix`. At other stages, Forge replies on the PR explaining the command is not applicable at the current workflow stage.

#### CI evaluation — `evaluate_ci_status`

Filter out skipped checks before determining pass/fail:

```python
ci_skipped_checks = state.get("ci_skipped_checks", [])

def is_skipped(check: dict) -> bool:
    name = check.get("name", "")
    return any(skip.lower() in name.lower() for skip in ci_skipped_checks)

for check in check_runs:
    if is_skipped(check):
        continue   # infrastructure skip — treat as passing
    ...
```

Skipped checks are not included in `ci_failed_checks`. If all remaining (non-skipped) checks pass, CI is considered passed.

#### Feedback comments

**GitHub PR reply** (immediately after skip is applied):
```
✅ CI gate skipped by @eshulman2

The following check will be treated as passing for this PR:
- `Run acceptance tests against OpenStack epoxy`

All other CI checks still apply. Re-evaluating CI status now.
```

**Jira audit comment** (on the linked ticket):
```
*CI gate skipped on GitHub PR by eshulman2:*
- `Run acceptance tests against OpenStack epoxy`

Skipped via `/forge skip-gate` on PR #759. Review accordingly.
```

**If check name doesn't match any failed check:**
```
⚠️ No failed check matching "epoxy" found.

Current failed checks:
- `Run acceptance tests against OpenStack epoxy`
- `Run acceptance tests against OpenStack flamingo`

Use the exact check name or a unique substring.
```

### User Experience

```
# CI is failing on one environment. Forge has tried 5 fixes with no luck.
# Engineer reviews logs — DevStack quota exhaustion, not a code issue.

[PR #759 comment by eshulman2]
/forge skip-gate Run acceptance tests against OpenStack epoxy

[Forge reply on PR #759]
✅ CI gate skipped by @eshulman2
- `Run acceptance tests against OpenStack epoxy`
Re-evaluating CI status now...

[Forge, moments later, on PR #759]
All CI checks passed (1 skipped by human override).
Ready for human review.

[Forge, on AISOS-376 Jira ticket]
CI gate skipped on GitHub PR by eshulman2:
- `Run acceptance tests against OpenStack epoxy`
Workflow proceeding to human review.
```

## Alternatives Considered

| Alternative | Pros | Cons | Why Not |
|-------------|------|------|---------|
| Jira comment command (`@forge skip-gate`) | Consistent with `@forge ask` | CI is a GitHub concern — control belongs next to where the failure lives | Mismatch between where the check fails and where it's skipped |
| New Jira label (`forge:skip-epoxy`) | Simple to detect | Labels encode data — ugly, doesn't scale across projects | Labels are for workflow state, not payload data |
| Config file in repo (`.forge/skip-checks.yml`) | Version-controlled, auditable | Requires a commit; can't target a single PR's failing check | Too heavyweight; affects all future runs of the same check |
| Blanket skip-all command | Simple | Masks real failures | Must require explicit check name — human must acknowledge what they're skipping |

## Implementation Plan

### Phases

1. **Phase 1: State + evaluator filtering** — Add `ci_skipped_checks` to `CIIntegrationState`, filter in `evaluate_ci_status`. (~2 hours)
2. **Phase 2: Comment detection** — Parse `/forge skip-gate` and `/forge unskip-gate` from `issue_comment` GitHub webhook in `_handle_resume_event`. (~2 hours)
3. **Phase 3: Feedback comments** — Post GitHub reply and Jira audit comment when skip is applied; post "check not found" error when name doesn't match. (~2 hours)
4. **Phase 4: Tests** — Unit tests for skip filtering in evaluator, command detection in worker, unskip path, and "not found" error path. (~half day)

### Dependencies

- [ ] `ci_skipped_checks` added to `create_initial_feature_state` and `create_initial_bug_state`
- [ ] GitHub webhook must deliver `issue_comment` events — already configured
- [ ] GitHub App needs `issues: write` or `pull-requests: write` permission to post reply comments — verify this is already granted
- [ ] `patch_checkpoint.py` should support list-valued fields for manual skip injection if needed

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| User skips a check that is failing due to a real code bug | Med | High | Jira audit comment warns reviewers; PR comment is visible to all reviewers; skip requires naming the specific check |
| Substring match is too broad and skips an unintended check | Low | Med | Log which checks matched the substring; if multiple checks match, require a more specific name and list matches |
| Skips persist across pushes and hide a later-introduced bug | Low | Med | Skipped checks listed in PR; `unskip-gate` removes them; auto-clear on PR close/merge |
| Command used at wrong workflow stage | Low | Low | Worker validates `current_node`; posts explanation if inapplicable |

## Open Questions

- [X] Should skips auto-reset when a new commit is pushed to the PR (requiring re-issuance for persistent infra issues), or persist until explicitly unskipped? persist until explicit unskip
- [X] Should there be a per-PR maximum number of skippable checks to prevent abuse? no
- [X] Should a skipped check trigger a required reviewer acknowledgement checkbox in the PR description? No
