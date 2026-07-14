# Forge Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          External Systems                               │
│                                                                         │
│   ┌──────────┐   ┌──────────┐   ┌──────────────────────────────────┐    │
│   │   Jira   │   │  GitHub  │   │      Langfuse (Observability)    │    │
│   └────┬─────┘   └────┬─────┘   └──────────────────────────────────┘    │
│        │              │                                                 │
└────────┼──────────────┼─────────────────────────────────────────────────┘
         │ webhooks     │ webhooks
         v              v
┌─────────────────────────────────────────────────────────────────────────┐
│                       FastAPI Server (:8000)                            │
│                                                                         │
│   POST /api/v1/webhooks/jira     POST /api/v1/webhooks/github           │
│   GET  /api/v1/health            GET  /metrics                          │
│                                                                         │
└────────────────────────────┬────────────────────────────────────────────┘
                             │ enqueue events
                             v
┌─────────────────────────────────────────────────────────────────────────┐
│                             Redis                                       │
│                                                                         │
│   Streams: forge:events:jira      State: AsyncRedisSaver                │
│            forge:events:github    LangGraph checkpointing               │
│   Consumer group: forge-workers   Per-ticket thread IDs (AISOS-123)     │
│                                                                         │
└────────────────────────────┬────────────────────────────────────────────┘
                             │ dequeue + dispatch
                             v
┌─────────────────────────────────────────────────────────────────────────┐
│                        WorkflowRouter                                   │
│                                                                         │
│   Routes by Jira issue type:                                            │
│     Feature/Story --> FeatureWorkflow (StateGraph)                      │
│     Bug           --> BugWorkflow     (StateGraph)                      │
│                                                                         │
│   ┌──────────────────────────────┐   ┌──────────────────────────────┐   │
│   │      Feature Workflow        │   │        Bug Workflow          │   │
│   │                              │   │                              │   │
│   │  generate_prd                │   │  triage_check                │   │
│   │    >> prd_approval_gate      │   │    >> triage_gate            │   │
│   │  generate_spec               │   │  analyze_bug                 │   │
│   │    >> spec_approval_gate     │   │    <> reflect_rca (up to 3x) │   │
│   │  decompose_epics             │   │    >> rca_option_gate        │   │
│   │    >> plan_approval_gate     │   │  plan_bug_fix                │   │
│   │  generate_tasks              │   │    >> plan_approval_gate     │   │
│   │    >> task_approval_gate     │   │  decompose_plan              │   │
│   │──────────────────────────────│   │──────────────────────────────│   │
│   │  task_router (per-repo)      │   │  Shared impl path:           │   │
│   │  setup_workspace             │   │    (same nodes as Feature)   │   │
│   │  implement_task              │   │                              │   │
│   │  local_review                │   │  Post-merge:                 │   │
│   │  update_documentation        │   │    post_merge_summary --> END│   │
│   │  create_pr                   │   │                              │   │
│   │  teardown_workspace          │   └──────────────────────────────┘   │
│   │──────────────────────────────│                                      │
│   │  wait_for_ci_gate            │                                      │
│   │  ci_evaluator <-- ci_fix     │                                      │
│   │  >> human_review_gate        │                                      │
│   │  complete_tasks              │                                      │
│   │  aggregate_epic_status       │                                      │
│   │  aggregate_feature_status    │                                      │
│   │    --> END                   │                                      │
│   └──────────────────────────────┘                                      │
│                                                                         │
│   >> = human checkpoint (auto-approved with forge:yolo label)           │
│                                                                         │
└────────────────────────────┬────────────────────────────────────────────┘
                             v
              ┌──────────────┼──────────────┐
              │ LLM calls                   │ LLM calls
              v                             v
┌────────────────────────────┐   ┌────────────────────────────────────────┐
│  LLM Backends              │   │  Podman Container (ephemeral)          │
│                            │   │                                        │
│  Anthropic API (Claude)    │   │  ┌──────────────────────────────────┐  │
│  Vertex AI (Claude)        │   │  │ Deep Agents (library) + MCP      │  │
│  Vertex AI (Gemini)        │   │  │ /task.json (task description)    │  │
│                            │<->│  │ /workspace (repo mounted)        │  │
│  Called by orchestrator    │   │  │ commits changes locally          │  │
│  nodes and container       │   │  └──────────────────────────────────┘  │
│  agents (bidirectional)    │   │                                        │
└────────────────────────────┘   └────────────────────────────────────────┘
```

## Feature Ticket Lifecycle

```
Jira ticket created + labeled "forge:managed" (type: Feature or Story)
  |
  v
generate_prd -- AI drafts Product Requirements Document
  |
  v
>> prd_approval_gate -- wait for approval (Jira comment or proposals PR)
  |
  v
generate_spec -- AI drafts Technical Specification
  |
  v
>> spec_approval_gate
  |
  v
decompose_epics -- AI breaks spec into Jira Epics
  |
  v
>> plan_approval_gate
  |
  v
generate_tasks -- AI creates implementation Tasks under Epics
  |
  v
>> task_approval_gate
  |
  v
task_router -- group tasks by target repo
  |
  v (per repo)
setup_workspace -- clone repo, create branch
  |
  v
implement_task -- Podman container + Deep Agents writes code
  |
  v
local_review -- AI reviews diff, fixes issues (up to 2 passes)
  |
  v
update_documentation -- update stale docs
  |
  v
create_pr -- open GitHub PR
  |
  v
teardown_workspace -- cleanup (loop back if more repos)
  |
  v
wait_for_ci_gate -- wait for CI checks
  |
  v
ci_evaluator --+-- pass ------+
               +-- fail ---+  |
                           |  |
             attempt_ci_fix   |
              (up to 5x)      |
                           |  |
               +-----------+  |
               |              |
               v              v
>> human_review_gate -- wait for PR approval
  |                    (changes_requested --> implement_review --> CI loop)
  v
complete_tasks --> aggregate_epic_status --> aggregate_feature_status --> END

>> = human checkpoint (auto-approved when forge:yolo label is set)
```

## Bug Ticket Lifecycle

```
Jira ticket created + labeled "forge:managed" (type: Bug)
  |
  v
triage_check -- validate bug report has required fields
  |
  v
>> triage_gate -- wait for reporter update if incomplete
  |
  v
analyze_bug <--+
  |            |
  +--- reflect_rca (up to 3 reflection cycles)
  |
  v
>> rca_option_gate -- present fix options, user selects ">option N"
  |
  v
plan_bug_fix -- AI generates fix plan
  |
  v
>> plan_approval_gate
  |
  v
decompose_plan -- break into tasks
  |
  v
setup_workspace --> implement --> local_review --> create_pr --> CI --> review
  |
  v
post_merge_summary --> END
```

## Data Flow Summary

```
Inbound events:     Jira/GitHub webhooks --> FastAPI --> Redis Streams
State persistence:  Redis (LangGraph AsyncRedisSaver, keyed by ticket)
LLM calls:         Orchestrator nodes --> Claude/Gemini (Anthropic / Vertex AI)
                    Container agents  --> Claude/Gemini (same backends)
Code execution:    implement_task --> Podman container --> Deep Agents (library)
Outbound actions:  Jira (comments, labels, transitions)
                   GitHub (PRs, branches, reviews)
Observability:     Langfuse (LLM traces, workflow spans, costs)
```
