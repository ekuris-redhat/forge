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
│   GET  /api/v1/health           GET  /api/v1/metrics                    │
│                                                                         │
└────────────────────────────┬────────────────────────────────────────────┘
                             │ enqueue events
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     Redis Streams ("forge:events")                       │
│                                                                         │
│   Consumer group: forge-workers        State: AsyncRedisSaver            │
│   Per-ticket thread IDs (AISOS-123)    LangGraph checkpointing          │
│                                                                         │
└────────────────────────────┬────────────────────────────────────────────┘
                             │ dequeue + dispatch
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     LangGraph Orchestrator                               │
│                                                                         │
│   Orchestrator.resume(event) → StateGraph(WorkflowState)                │
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    Workflow Nodes                                │   │
│   │                                                                 │   │
│   │   CLASSIFY ─┬─► [Bug]  TRIAGE → RCA_OPTIONS → RCA_GATE → RCA   │   │
│   │             │                                       │           │   │
│   │             └─► [Feature] ──────────────────────────┤           │   │
│   │                                                     ▼           │   │
│   │              PRD → PRD_GATE ─► SPEC → SPEC_GATE                 │   │
│   │                                         │                       │   │
│   │                                         ▼                       │   │
│   │              PLAN → PLAN_GATE ─► TASKS → TASK_GATE              │   │
│   │                                             │                   │   │
│   │                                             ▼                   │   │
│   │              IMPLEMENT ─► PR_CREATE ─► CI_GATE ◄─┐              │   │
│   │                                          │       │              │   │
│   │                              CI_EVALUATOR┤  CI_FIX (retry)      │   │
│   │                                          │       │              │   │
│   │                                          ▼       │              │   │
│   │                              HUMAN_REVIEW_GATE───┘              │   │
│   │                                          │                      │   │
│   │                                    MERGE → DONE                 │   │
│   │                                                                 │   │
│   │   ⏸ Gates = human checkpoints (skipped with forge:yolo label)   │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└───────────────┬─────────────────────────────┬───────────────────────────┘
                │                             │
                ▼                             ▼
┌──────────────────────────┐   ┌──────────────────────────────────────────┐
│   Claude LLM             │   │   Podman Container (ephemeral)           │
│                          │   │                                          │
│   Anthropic API          │   │   ┌─────────────────────────────────┐    │
│   or Vertex AI           │   │   │  Deep Agents + MCP tools        │    │
│                          │   │   │  .forge/task.json                │    │
│   Used by: classify,     │   │   │  workspace mounted               │    │
│   triage, RCA, PRD,      │   │   │  commits changes locally         │    │
│   spec, plan, CI eval    │   │   └─────────────────────────────────┘    │
│                          │   │                                          │
└──────────────────────────┘   └──────────────────────────────────────────┘
```

## Ticket Lifecycle

```
Jira ticket created + labeled "forge:managed"
  │
  ▼
CLASSIFY ── Claude determines: bug or feature?
  │
  ├── Bug ────► TRIAGE → RCA_OPTIONS → ⏸ RCA_OPTION_GATE → RCA_DEEP_DIVE
  │                                          (user picks ">option N")
  │
  └── Feature ─────────────────────────────────────┐
                                                    │
  ◄─────────────────────────────────────────────────┘
  │
  ▼
PRD ── generate requirements ── ⏸ PRD_GATE (Jira or proposals PR)
  │
  ▼
SPEC ── generate tech design ── ⏸ SPEC_GATE
  │
  ▼
PLAN ── generate impl plan ──── ⏸ PLAN_GATE
  │
  ▼
TASKS ── break into work items ─ ⏸ TASK_GATE
  │
  ▼
IMPLEMENT ── Podman container + Deep Agents executes code
  │
  ▼
PR_CREATE ── open GitHub PR
  │
  ▼
CI_GATE ── wait for checks ──► CI_EVALUATOR
  │                                │
  │               ┌── pass ────────┤
  │               │                └── fail ──► ATTEMPT_CI_FIX ─┐
  │               │                                  (retry ≤N) │
  │               │                ◄────────────────────────────┘
  ▼               ▼
HUMAN_REVIEW_GATE ── ⏸ wait for PR approval
  │
  ▼
MERGE ── merge PR ──► DONE ✓

⏸ = human checkpoint (auto-approved when forge:yolo label is set)
```

## Data Flow Summary

```
Inbound events:     Jira/GitHub webhooks → FastAPI → Redis Streams
State persistence:  Redis (LangGraph AsyncRedisSaver, keyed by ticket)
LLM calls:         Orchestrator nodes → Claude (Anthropic API / Vertex AI)
Code execution:    IMPLEMENT node → Podman container → Deep Agents
Outbound actions:  Jira (comments, labels, transitions)
                   GitHub (PRs, branches, reviews)
Observability:     Langfuse (LLM traces, workflow spans, costs)
```
