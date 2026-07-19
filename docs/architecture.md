# Forge Architecture

Forge is an AI-powered SDLC orchestrator. It listens for Jira and GitHub events, routes them through LangGraph workflows, and drives implementation end-to-end, from requirements through code generation, CI repair, and human review. This page describes the major components and how they connect.

## System Overview

Forge is built from six layers that form a pipeline from external events to code changes.

- **External Systems:** Jira (ticket lifecycle), GitHub (PRs, CI, code review), and Langfuse (observability and cost tracking). Forge receives webhooks from Jira and GitHub and writes back to both throughout the workflow.
- **FastAPI Server:** A lightweight API layer that validates incoming webhooks and enqueues them as events. It also exposes health and Prometheus metrics endpoints.
- **Redis:** Serves two roles: an event bus (Redis Streams with consumer groups for reliable delivery) and a state store (LangGraph's AsyncRedisSaver checkpoints workflow state per ticket so workflows survive restarts).
- **WorkflowRouter:** The orchestration core. Incoming events are dispatched to one of three LangGraph StateGraph workflows based on Jira issue type: **FeatureWorkflow** (Feature/Story), **BugWorkflow** (Bug), or **TaskTakeoverWorkflow** (Task/Epic). Each workflow is a graph of nodes connected by conditional edges, with human approval gates at key decision points.
- **Podman Container:** Implementation runs in ephemeral rootless containers. Each container mounts the target repository, receives a task description, and uses Deep Agents (an AI coding library) with MCP tool access to make changes and commit them locally. The orchestrator handles pushing and PR creation after the container exits.
- **LLM Backends:** Claude and Gemini models are called bidirectionally. Orchestrator nodes call them for planning and review, and container agents call them for code generation. Forge supports Anthropic's direct API and Vertex AI, selected by configuration.

```mermaid
flowchart TD
    subgraph External["External Systems"]
        Jira
        GitHub
        Langfuse["Langfuse (Observability)"]
    end

    subgraph Gateway["FastAPI Gateway (:8000)"]
        JiraWH["POST /webhooks/jira"]
        GitHubWH["POST /webhooks/github"]
    end

    subgraph Queue["Redis"]
        Streams["Streams: forge:events:jira\nforge:events:github"]
        State["AsyncRedisSaver\nLangGraph checkpointing"]
    end

    subgraph Workers["Worker Processes (consumer group: forge-workers)"]
        Router{"WorkflowRouter\nroute by issue type"}
        Feature["FeatureWorkflow\n(Feature/Story)"]
        Bug["BugWorkflow\n(Bug)"]
        Task["TaskTakeoverWorkflow\n(Task/Epic)"]
    end

    subgraph Container["Podman Container (ephemeral)"]
        Agent["Deep Agents + MCP\n/workspace (repo mounted)"]
    end

    LLM["LLM Backends\nAnthropic API (Claude)\nVertex AI (Claude/Gemini)"]

    Jira -- webhooks --> JiraWH
    GitHub -- webhooks --> GitHubWH
    JiraWH --> Streams
    GitHubWH --> Streams
    Streams --> Router
    Router --> Feature
    Router --> Bug
    Router --> Task
    Feature --> Container
    Bug --> Container
    Task --> Container
    Workers <--> LLM
    Container <--> LLM
    Workers --> Jira
    Workers --> GitHub
    Workers --> Langfuse
```

## Feature Ticket Lifecycle

The Feature workflow handles the largest scope of work. It takes a Jira Feature or Story from a one-line description through a full planning pipeline (PRD, technical spec, epic decomposition, and task breakdown) before any code is written. Each planning stage produces an artifact posted to Jira (or as a GitHub PR in the proposals repo) and pauses at a human approval gate. Reviewers can approve, request revisions with a "!" comment, or ask questions with "?" without advancing the workflow.

Once all planning is approved, Forge groups tasks by target repository and implements them in parallel. Each task runs in its own Podman container. After implementation, Forge reviews the diff, updates documentation, and opens a PR. If CI fails, Forge analyzes the failure and attempts automated fixes (up to 5 times). When CI passes, the workflow pauses for human PR review. Review feedback triggers another implementation-CI cycle. After merge, Forge aggregates status up through tasks, epics, and the parent feature.

```mermaid
flowchart TD
    A["Jira ticket created\nforge:managed (Feature/Story)"] --> B[generate_prd]
    B --> C[">> prd_approval_gate"]
    C --> D[generate_spec]
    D --> E[">> spec_approval_gate"]
    E --> F[decompose_epics]
    F --> G[">> plan_approval_gate"]
    G --> H[generate_tasks]
    H --> I[">> task_approval_gate"]
    I --> J["task_router (per-repo)"]

    J --> K[setup_workspace]
    K --> L["implement_task\n(Podman + Deep Agents)"]
    L --> M[local_review]
    M -->|"needs work (up to 2x)"| L
    M --> N[update_documentation]
    N --> O[create_pr]
    O --> P["teardown_workspace"]
    P -->|more repos| K

    P --> Q[wait_for_ci_gate]
    Q --> R{ci_evaluator}
    R -->|fail| S["attempt_ci_fix\n(up to 5x)"]
    S --> Q
    R -->|pass| T[">> human_review_gate"]
    T -->|changes_requested| U[implement_review]
    U --> Q
    T -->|merged| V["complete_tasks\naggregate_epic_status\naggregate_feature_status\nEND"]
```

`>>` = human checkpoint (auto-approved when forge:yolo label is set)

## Bug Ticket Lifecycle

The Bug workflow starts with triage. Forge checks whether the ticket has enough context to investigate. If information is missing, it pauses and asks the reporter to fill in the gaps. Once the report is sufficient, Forge performs root cause analysis with up to three reflection cycles to refine its understanding. It then presents numbered fix options and waits for the user to select one with a ">option N" comment.

After the user selects a fix approach, Forge generates a fix plan, pauses for approval, and decomposes it into implementation tasks. From there the workflow shares the same implementation path as the Feature workflow: container execution, local review, PR creation, CI repair loop, and human review. After the PR is merged, Forge posts a summary of the fix back to the Jira ticket.

```mermaid
flowchart TD
    A["Jira ticket created\nforge:managed (Bug)"] --> B[triage_check]
    B -->|missing fields| C[">> triage_gate"]
    C --> B
    B -->|sufficient| D[analyze_bug]
    D --> E{reflect_rca}
    E -->|"needs refinement (up to 3x)"| D
    E -->|"analysis complete"| F[">> rca_option_gate\nuser selects >option N"]
    F --> G[plan_bug_fix]
    G --> H[">> plan_approval_gate"]
    H --> I[decompose_plan]

    I --> J[setup_workspace]
    J --> K["implement_bug_fix\n(Podman + Deep Agents)"]
    K --> L[local_review]
    L -->|"needs work"| K
    L --> M[update_documentation]
    M --> N[create_pr]
    N --> O[teardown_workspace]
    O -->|more repos| J

    O --> P[wait_for_ci_gate]
    P --> Q{ci_evaluator}
    Q -->|fail| R["attempt_ci_fix"]
    R --> P
    Q -->|pass| S[">> human_review_gate"]
    S -->|changes_requested| T[implement_review]
    T --> P
    S -->|merged| U[post_merge_summary]
    U --> V[END]
```

## Task Ticket Lifecycle

The Task workflow is the shortest path from ticket to PR. It handles standalone Jira Tasks and Epics that are already scoped enough to implement directly, without PRD, spec, or epic decomposition. Forge triages the ticket for sufficient context, generates an implementation plan, and pauses for approval. At the approval gate, reviewers can ask questions ("?"), request revisions ("!"), or approve to proceed.

After approval, implementation follows the same container-based execution as the other workflows: Forge sets up a workspace, runs the changes in a Podman container with Deep Agents, reviews the output for quality (up to 2 retries), and opens a PR. The CI repair loop and human review gate work identically to the Feature and Bug workflows.

```mermaid
flowchart TD
    A["Jira ticket created\nforge:managed (Task/Epic)"] --> B[triage_check]
    B -->|missing context| C[">> triage_gate\nforge:task-triage-pending"]
    C --> B
    B -->|sufficient| D[generate_plan]
    D --> E[">> task_plan_approval_gate\nforge:plan-pending"]
    E -->|"? question"| F[answer_question]
    F --> E
    E -->|"! feedback"| D
    E -->|approved| G[setup_workspace]

    G --> H["execute_task_changes\n(Podman + Deep Agents)"]
    H --> I[run_qualitative_review]
    I -->|"needs work (up to 2x)"| H
    I -->|adequate| J[create_pr]
    J --> K[teardown_workspace]
    K -->|more repos| G

    K --> L[wait_for_ci_gate]
    L --> M{ci_evaluator}
    M -->|fail| N["attempt_ci_fix"]
    N --> L
    M -->|pass| O[">> human_review_gate"]
    O -->|changes_requested| P[implement_review]
    P --> L
    O -->|merged| Q[complete_task_takeover]
```

## Data Flow Summary

- **Inbound events:** Jira/GitHub webhooks --> FastAPI --> Redis Streams
- **State persistence:** Redis (LangGraph AsyncRedisSaver, keyed by ticket)
- **LLM calls:** Orchestrator nodes and container agents --> Claude/Gemini (Anthropic / Vertex AI), bidirectional
- **Code execution:** implement_task --> Podman container --> Deep Agents (library)
- **Outbound actions:** Jira (comments, labels, transitions), GitHub (PRs, branches, reviews)
- **Observability:** Langfuse (LLM traces, workflow spans, costs)
