# Proposal: Q&A Mode for Generated Artifacts

**Author:** eshulman2
**Date:** 2026-04-14
**Status:** Implemented (2026-04-15)

## Open Questions (Resolved)

- **How long to retain generation history?** Delete on workflow completion
- **Store Q&A exchanges?** Yes, as structured Jira comment on approval
- **Summarize Q&A option?** No (MVP)
- **Prefix?** Support both `?` and `@forge ask`

## Summary

Enable users to ask questions about generated PRDs and specs without triggering regeneration. Comments starting with `?` or `@forge ask` are treated as questions rather than approval/rejection feedback, allowing clarifying discussions while keeping the workflow paused.

## Motivation

### Problem Statement

When a PRD or spec is generated, PMs and engineers often want to understand the reasoning behind decisions before approving. Currently, any comment is treated as feedback that triggers regeneration or workflow advancement.

Common questions that arise:
- "Why did you choose microservices over monolith?"
- "What alternatives did you consider for the auth approach?"
- "Can you explain the tradeoff you made here?"
- "How does this align with requirement X?"

### Current Workarounds

Users must either:
1. Approve blindly and ask questions later (poor UX)
2. Add comments and deal with unwanted regeneration
3. Use external channels (Slack, email) to discuss, losing context

## Proposal

### Overview

Combine question detection with stored generation context:

1. **Store generation context**: Save agent conversation when creating PRD/spec
2. **Detect questions**: Use explicit prefix to distinguish questions from feedback
3. **Respond without advancing**: Answer in Jira comment, keep workflow paused

### Detailed Design

#### New Workflow State

```python
# In WorkflowState
"qa_mode": bool  # Currently in Q&A mode
"qa_history": list[dict]  # Q&A exchanges for this ticket
```

#### Comment Classification

```python
def classify_comment(comment_text: str) -> Literal["question", "approval", "rejection", "feedback"]:
    text = comment_text.strip().lower()

    # Explicit question markers
    if text.startswith("?") or text.startswith("@forge ask"):
        return "question"

    # Existing approval/rejection detection
    if "approved" in text or "lgtm" in text:
        return "approval"

    return "feedback"
```

#### New Node: Answer Question

```python
async def answer_question(state: WorkflowState) -> WorkflowState:
    """Answer a question about generated artifact without advancing workflow."""

    # Load original generation context
    generation_history = load_generation_history(state["ticket_key"])

    # Load current artifact (PRD/spec)
    current_artifact = state.get("prd_content") or state.get("spec_content")

    # Build prompt with context
    answer = await agent.run(
        f"Based on your previous generation of this artifact, answer: {state['current_comment']}"
    )

    # Post answer to Jira
    await jira.add_comment(state["ticket_key"], answer)

    # Stay at current gate (don't advance)
    return {**state, "current_node": state["current_node"]}
```

#### Storage Location

Generation history stored as:
- `.forge/generation-history/{ticket_key}.json` in workspace, OR
- Jira attachment on the ticket

### User Experience

```
User comments: "?Why did you choose REST over GraphQL for the API?"

Forge responds (as Jira comment):
"Based on the requirements analysis:

1. The API primarily serves CRUD operations with predictable query patterns
2. REST provides simpler caching via HTTP semantics
3. The team has more REST experience (noted in constraints)

GraphQL was considered but deferred due to added complexity for the current scope.
See FR-003 in the PRD for the specific requirements that led to this decision."

[Workflow remains paused at approval gate]
```

## Alternatives Considered

| Alternative | Pros | Cons | Why Not |
|-------------|------|------|---------|
| Question detection only (no stored context) | Simple implementation | Inaccurate recall of original reasoning | May give inconsistent answers |
| Discussion mode via `forge:discuss` label | Unambiguous intent | Extra step for users, another label | Adds friction |
| Linked Confluence page | Persistent documentation | Requires Confluence, more complexity | Over-engineered for MVP |

## Implementation Plan

### Phases

1. **Phase 1: Comment Classification** - 2-3 days
   - Add `classify_comment()` function
   - Route questions to new node
   - Update worker event handling

2. **Phase 2: Context Storage** - 2-3 days
   - Save generation history during PRD/spec creation
   - Implement `load_generation_history()`
   - Choose storage location (attachment vs file)

3. **Phase 3: Answer Node** - 3-4 days
   - Implement `answer_question` node
   - Build prompt with context
   - Post response to Jira
   - Handle edge cases (no history found, etc.)

### Dependencies

- [ ] Jira comment parsing (exists)
- [ ] Agent infrastructure (exists)
- [ ] Storage mechanism for generation history

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Users spam questions | Low | Medium | Add rate limiting (e.g., 5 questions per artifact) |
| Context storage grows large | Medium | Low | Prune history after approval, compress |
| Answers inconsistent with artifact | Medium | Medium | Include artifact in prompt context |

## Open Questions

- [ ] How long to retain generation history after approval?
- [ ] Should Q&A exchanges be stored for future reference?
- [ ] Should there be a "summarize all Q&A" option before approval?
- [ ] What prefix is most intuitive? (`?`, `@forge ask`, `@forge explain`)

## References

- Original idea: `.forge/ideas/qa-mode-for-generated-artifacts.md`
