# Proposal: Retryable Blocked State via forge:retry

**Author:** eshulman2
**Date:** 2026-04-19
**Status:** Implemented

## Summary

When a workflow is blocked, Forge overwrites `current_node` with `"complete"`, making the blocked state indistinguishable from a successful terminal state. The `forge:retry` label therefore has no effect — the worker skips invocation thinking the workflow is done. This proposal fixes the state machine so blocked workflows can be retried without manually patching Redis.

## Motivation

### Problem Statement

`escalate_to_blocked` always sets `current_node = "complete"`, erasing which node triggered the escalation. The worker treats any checkpoint with `current_node == "complete"` as a terminal state and refuses to invoke the workflow. When a user adds the `forge:retry` label hoping to resume, nothing happens.

There is currently no way to retry a blocked ticket without directly patching the Redis checkpoint — which is not a user-accessible operation.

### Current Workarounds

Users must either abandon the ticket, create a new one, or have an engineer manually edit the Redis checkpoint to restore the correct `current_node` before adding `forge:retry`.

## Proposal

### Overview

Add an `is_blocked: bool` field to the base workflow state. `escalate_to_blocked` sets this flag instead of overwriting `current_node`. The failing node is preserved in state so `forge:retry` knows exactly where to resume. The worker's terminal-state check is updated to treat `is_blocked=True` as non-invocable, and the retry handler clears the flag before resuming.

**Core invariant:** retry always resumes at the node that failed — it never back-tracks to an earlier stage.

### Detailed Design

#### 1. State schema — `src/forge/workflow/base.py`

Add `is_blocked: bool` to `BaseState`. Initialize to `False` in `create_initial_feature_state` and `create_initial_bug_state`.

#### 2. `escalate_to_blocked` — `src/forge/workflow/nodes/ci_evaluator.py`

Remove `"current_node": "complete"` from the return dict. Add `"is_blocked": True`. All existing behavior (Jira label, error comment, generation context cleanup) is unchanged.

Before:
```python
return update_state_timestamp({
    **state,
    "ci_status": "blocked",
    "current_node": "complete",   # erases the failing node
    "generation_context": {},
    "qa_history": [],
})
```

After:
```python
return update_state_timestamp({
    **state,
    "is_blocked": True,
    "ci_status": "blocked",
    # current_node preserved — retry resumes here
    "generation_context": {},
    "qa_history": [],
})
```

#### 3. `forge:retry` handler — `src/forge/orchestrator/worker.py`

In `_handle_resume_event`, when `is_retry = True`, clear the blocked flag and reset the CI attempt counter alongside the existing resets:

```python
updated_state["is_blocked"] = False
updated_state["ci_fix_attempts"] = 0   # prevents immediately re-exhausting CI retries
```

`current_node`, `retry_count`, and `last_error` are already reset by the existing retry handler.

#### 4. Worker terminal/blocked check — `src/forge/orchestrator/worker.py`

Replace the terminal-only guard in `_process_workflow` with one that covers both cases:

```python
terminal_nodes = ("complete", "complete_tasks", "aggregate_feature_status")
is_terminal_or_blocked = (
    updated_values.get("current_node") in terminal_nodes
    or updated_values.get("is_blocked", False)
)

if is_terminal_or_blocked:
    logger.info(
        f"Workflow for {ticket_key} at "
        f"{'terminal' if updated_values.get('current_node') in terminal_nodes else 'blocked'} "
        f"state '{updated_values.get('current_node')}', skipping invocation"
    )
    await compiled_workflow.aupdate_state(config, updated_values)
    return
```

When `forge:retry` is used, step 3 clears `is_blocked` to `False` before this check runs, so invocation proceeds normally.

#### 5. `route_by_ticket_type` — `src/forge/workflow/feature/graph.py`

No changes required. The preserved `current_node` (e.g. `ci_evaluator`, `setup_workspace`, `implement_task`, `create_pr`) is already present in the existing routing table.

### User Experience

```
# Before: forge:retry does nothing — worker logs "terminal state, skipping"
# User adds forge:retry → Jira comment appears → worker receives event
#   → loads checkpoint → current_node="complete" → skips invocation → silence

# After:
# Workflow blocked at ci_evaluator → current_node="ci_evaluator", is_blocked=True
# User adds forge:retry → worker clears is_blocked, resets ci_fix_attempts
#   → resumes from ci_evaluator → workflow continues normally
```

**Retry behavior by failure point:**

| Blocked at | forge:retry resumes at | Additional reset |
|------------|------------------------|------------------|
| `ci_evaluator` | `ci_evaluator` | `ci_fix_attempts = 0` |
| `setup_workspace` | `setup_workspace` | — |
| `implement_task` | `implement_task` | `retry_count = 0` (existing) |
| `create_pr` | `create_pr` | — |
| Happy-path `complete` | No-op (not blocked) | — |

## Alternatives Considered

| Alternative | Pros | Cons | Why Not |
|-------------|------|------|---------|
| Store failing node in a separate `blocked_at_node` field | Doesn't touch `current_node` semantics | Two fields to keep in sync; routing logic would need to read `blocked_at_node` instead of `current_node` | More complex than needed |
| Keep `current_node = "complete"` and add a separate retry mechanism | No change to terminal detection | `forge:retry` would need to know what `current_node` to restore, requiring a `blocked_at_node` field anyway | Same complexity, worse semantics |
| Allow back-tracking to earlier stages on retry | More recovery flexibility | Ambiguous choice of which stage; risks re-running side effects (Jira ticket creation, PR creation) | Out of scope; a separate design decision |

## Implementation Plan

### Phases

1. **Phase 1:** State schema change + `escalate_to_blocked` fix — minimal diff, highest leverage. (~2 hours)
2. **Phase 2:** Worker terminal/blocked check + retry handler — completes the loop. (~2 hours)
3. **Phase 3:** Unit tests for new `is_blocked` paths in worker and escalation node. (~half day)

### Dependencies

- [ ] No external dependencies

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Existing checkpoints in Redis have `current_node="complete"` from a blocked escalation | Med | Low | On retry these would still appear terminal; operator can clear manually if needed. New blocks after this change will work correctly. |
| `ci_fix_attempts` reset allows infinite retry loops | Low | Med | User must explicitly add `forge:retry` each time; not automatic |

## Open Questions

- [X] Should `ci_fix_attempts` always be reset on `forge:retry`, or only when `current_node == "ci_evaluator"`? Resetting it unconditionally is simpler but slightly surprising when retrying a non-CI failure. answer: reset it unconditionally
- [X] Should `forge:retry` on a happy-path terminal state post a Jira comment explaining it was ignored, to avoid user confusion? answer: yes
