# Forge Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          External Systems                               │
│                                                                         │
│   ┌──────────┐    ┌──────────┐    ┌───────────┐    ┌────────────────┐  │
│   │   Jira   │    │  GitHub  │    │   Deep    │    │   Langfuse     │  │
│   │          │    │          │    │   Agents  │    │ (Observability)│  │
│   └────┬─────┘    └────┬─────┘    └───────────┘    └────────────────┘  │
│        │               │                                                │
└────────┼───────────────┼────────────────────────────────────────────────┘
         │ webhooks       │ webhooks
         ▼               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        FastAPI Server (:8000)                            │
│                                                                         │
│   POST /api/v1/webhooks/jira    POST /api/v1/webhooks/github            │
│   GET  /api/v1/health           GET  /metrics                           │
│                                                                         │
└────────────────────────────┬────────────────────────────────────────────┘
                             │ enqueue events
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          Redis                                          │
│                                                                         │
│   Streams: forge:events:jira       State: AsyncRedisSaver                │
│            forge:events:github     LangGraph checkpointing               │
│   Consumer group: forge-workers    Per-ticket thread IDs (AISOS-123)     │
│                                                                         │
└────────────────────────────┬────────────────────────────────────────────┘
                             │ dequeue + dispatch
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     WorkflowRouter                                      │
│                                                                         │
│   Selects graph based on Jira issue type:                                │
│     Feature/Story → FeatureWorkflow (StateGraph)                         │
│     Bug           → BugWorkflow     (StateGraph)                         │
│                                                                         │
│   ┌──────────────────────────────┐  ┌────────────────────────────────┐  │
│   │      Feature Workflow        │  │        Bug Workflow            │  │
│   │                              │  │                                │  │
│   │  generate_prd                │  │  triage_check                  │  │
│   │    → ⏸ prd_approval_gate    │  │    → ⏸ triage_gate            │  │
│   │  generate_spec               │  │  analyze_bug ◄─┐              │  │
│   │    → ⏸ spec_approval_gate   │  │    → reflect_rca ─┘ (≤3x)    │  │
│   │  decompose_epics             │  │    → ⏸ rca_option_gate       │  │
│   │    → ⏸ plan_approval_gate   │  │  plan_bug_fix                 │  │
│   │  generate_tasks              │  │    → ⏸ plan_approval_gate    │  │
│   │    → ⏸ task_approval_gate   │  │  decompose_plan               │  │
│   │  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │  │  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │  │
│   │  task_router (per-repo)      │  │  Shared implementation path:  │  │
│   │  setup_workspace             │  │    (same nodes as Feature)    │  │
│   │  implement_task              │  │                                │  │
│   │  local_review                │  │  Post-merge:                   │  │
│   │  update_documentation        │  │    post_merge_summary → END   │  │
│   │  create_pr                   │  │                                │  │
│   │  teardown_workspace          │  └────────────────────────────────┘  │
│   │  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │                                     │
│   │  wait_for_ci_gate            │                                     │
│   │  ci_evaluator ◄── ci_fix     │                                     │
│   │  ⏸ human_review_gate        │                                     │
│   │  complete_tasks              │                                     │
│   │  aggregate_epic_status       │                                     │
│   │  aggregate_feature_status    │                                     │
│   │    → END                     │                                     │
│   └──────────────────────────────┘                                     │
│                                                                         │
│   ⏸ = human checkpoint (auto-approved with forge:yolo label)            │
│                                                                         │
└───────────────┬─────────────────────────────┬───────────────────────────┘
                │                             │
                ▼                             ▼
┌──────────────────────────┐   ┌──────────────────────────────────────────┐
│   LLM Backends           │   │   Podman Container (ephemeral)           │
│                          │   │                                          │
│   Anthropic API (Claude) │   │   ┌─────────────────────────────────┐    │
│   Vertex AI (Claude)     │   │   │  Deep Agents + MCP tools        │    │
│   Vertex AI (Gemini)     │   │   │  /task.json (task description)  │    │
│                          │   │   │  /workspace (repo mounted)      │    │
│   Used by: PRD, spec,    │   │   │  commits changes locally         │    │
│   plan, RCA, triage,     │   │   └─────────────────────────────────┘    │
│   code review, CI eval   │   │                                          │
└──────────────────────────┘   └──────────────────────────────────────────┘
```

## Feature Ticket Lifecycle

```
Jira ticket created + labeled "forge:managed" (type: Feature or Story)
  │
  ▼
generate_prd ── AI drafts Product Requirements Document
  │
  ▼
⏸ prd_approval_gate ── wait for approval (Jira comment or proposals PR)
  │
  ▼
generate_spec ── AI drafts Technical Specification
  │
  ▼
⏸ spec_approval_gate
  │
  ▼
decompose_epics ── AI breaks spec into Jira Epics
  │
  ▼
⏸ plan_approval_gate
  │
  ▼
generate_tasks ── AI creates implementation Tasks under Epics
  │
  ▼
⏸ task_approval_gate
  │
  ▼
task_router ── group tasks by target repo
  │
  ▼ (per repo)
setup_workspace ── clone repo, create branch
  │
  ▼
implement_task ── Podman container + Deep Agents writes code
  │
  ▼
local_review ── AI reviews diff, fixes issues (≤2 passes)
  │
  ▼
update_documentation ── update stale docs
  │
  ▼
create_pr ── open GitHub PR
  │
  ▼
teardown_workspace ── cleanup (loop back if more repos)
  │
  ▼
wait_for_ci_gate ── wait for CI checks
  │
  ▼
ci_evaluator ─┬─ pass ──────────────────────────┐
              └─ fail → attempt_ci_fix (≤5x) ───┘
  │
  ▼
⏸ human_review_gate ── wait for PR approval
  │                     (changes_requested → implement_review → CI loop)
  ▼
complete_tasks → aggregate_epic_status → aggregate_feature_status → END

⏸ = human checkpoint (auto-approved when forge:yolo label is set)
```

## Bug Ticket Lifecycle

```
Jira ticket created + labeled "forge:managed" (type: Bug)
  │
  ▼
triage_check ── validate bug report has required fields
  │
  ▼
⏸ triage_gate ── wait for reporter update if incomplete
  │
  ▼
analyze_bug ◄──┐
  │            │ reflect_rca (up to 3 reflection cycles)
  └────────────┘
  │
  ▼
⏸ rca_option_gate ── present fix options, user selects ">option N"
  │
  ▼
plan_bug_fix ── AI generates fix plan
  │
  ▼
⏸ plan_approval_gate
  │
  ▼
decompose_plan ── break into tasks
  │
  ▼
setup_workspace → implement → local_review → create_pr → CI → review
  │
  ▼
post_merge_summary → END
```

## Data Flow Summary

```
Inbound events:     Jira/GitHub webhooks → FastAPI → Redis Streams
State persistence:  Redis (LangGraph AsyncRedisSaver, keyed by ticket)
LLM calls:         Orchestrator nodes → Claude/Gemini (Anthropic API / Vertex AI)
Code execution:    implement_task → Podman container → Deep Agents
Outbound actions:  Jira (comments, labels, transitions)
                   GitHub (PRs, branches, reviews)
Observability:     Langfuse (LLM traces, workflow spans, costs)
```
