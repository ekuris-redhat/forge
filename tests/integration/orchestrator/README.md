# Orchestrator Integration Tests

This directory contains integration tests for the workflow orchestrator and related node implementations.

## Test Files

### test_task_implementation_status.py

Integration tests for task implementation status comments (SC-002 specification).

**Purpose**: Verify that Jira status comments are posted correctly during task implementation workflow execution.

**Test Scenarios**:

1. **TS-003: Single task receives start and completion comments**
   - `test_single_task_receives_start_comment`: Verifies "🔨 Forge is implementing this task." is posted
   - `test_single_task_receives_completion_comment_on_success`: Verifies both start and "✅ Implementation complete. Running local code review before PR." comments
   - `test_single_task_no_completion_comment_on_failure`: Verifies no completion comment when task fails

2. **TS-013: Multiple tasks receive independent comments (no cross-contamination)**
   - `test_multiple_tasks_receive_independent_start_comments`: Verifies each task gets its own start comment with correct task_key
   - `test_multiple_tasks_receive_independent_completion_comments`: Verifies each task gets completion comments independently without cross-contamination

3. **Failure Scenarios**
   - `test_task_implementation_fails_midway_no_completion_comment`: Verifies no completion comment when container fails
   - `test_multiple_tasks_partial_failure_only_successful_get_completion`: Verifies only successful tasks get completion comments

4. **Error Handling**
   - `test_workflow_continues_when_start_comment_posting_fails`: Verifies workflow continues when Jira start comment fails
   - `test_workflow_continues_when_completion_comment_posting_fails`: Verifies workflow continues when Jira completion comment fails
   - `test_workflow_continues_when_all_comment_posting_fails`: Verifies workflow continues even with complete Jira outage

**Running the tests**:
```bash
uv run pytest tests/integration/orchestrator/test_task_implementation_status.py -v
```

**Mock Strategy**:
- JiraClient is mocked to avoid external API calls
- ContainerRunner is mocked with configurable success/failure results
- Tests verify exact comment text matches specification
- Tests verify workflow continues despite Jira failures (error suppression)

### test_workflow_execution.py

Integration tests for LangGraph workflow execution.

**Status**: Currently skipped pending update for pluggable workflows architecture.

### test_task_handoff.py

Integration tests for task handoff between workflow nodes.

## Running All Integration Tests

```bash
# Run all orchestrator integration tests
uv run pytest tests/integration/orchestrator/ -v

# Run specific test file
uv run pytest tests/integration/orchestrator/test_task_implementation_status.py -v

# Run specific test class
uv run pytest tests/integration/orchestrator/test_task_implementation_status.py::TestTaskImplementationStatusCommentsTS003 -v

# Run specific test
uv run pytest tests/integration/orchestrator/test_task_implementation_status.py::TestTaskImplementationStatusCommentsTS003::test_single_task_receives_start_comment -v
```

## Test Maintenance

When updating task implementation behavior:

1. Update the corresponding tests in `test_task_implementation_status.py`
2. Ensure exact comment text matches the specification
3. Verify error handling tests still pass (workflow should never fail due to comment posting)
4. Run the full test suite to check for regressions

## Dependencies

These integration tests require:
- pytest
- pytest-asyncio (for async test support)
- unittest.mock (standard library)
- forge.workflow modules
- forge.integrations.jira modules

## Test Coverage Checklist

- [x] TS-003: Single task receives both start and completion comments
- [x] TS-013: Multiple tasks receive independent comments (no cross-contamination)
- [x] No completion comment when task implementation fails
- [x] Workflow continues when comment posting fails
- [x] Exact comment text verification
- [x] Error logging verification (via caplog fixture)
