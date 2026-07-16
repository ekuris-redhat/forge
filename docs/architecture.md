# Forge Architecture

## System Overview

```mermaid
flowchart TD
    subgraph External["External Systems"]
        Jira
        GitHub
        Langfuse["Langfuse (Observability)"]
    end

    subgraph API["FastAPI Server (:8000)"]
        JiraWH["POST /webhooks/jira"]
        GitHubWH["POST /webhooks/github"]
    end

    subgraph Queue["Redis"]
        Streams["Streams: forge:events:jira\nforge:events:github"]
        State["AsyncRedisSaver\nLangGraph checkpointing"]
    end

    subgraph Router["WorkflowRouter"]
        Route{"Route by\nissue type"}
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
    Streams --> Route
    Route --> Feature
    Route --> Bug
    Route --> Task
    Feature --> Container
    Bug --> Container
    Task --> Container
    Router <--> LLM
    Container <--> LLM
    Router --> Jira
    Router --> GitHub
    Router --> Langfuse
```

## Feature Ticket Lifecycle

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
    T -->|approved| V["complete_tasks\naggregate_epic_status\naggregate_feature_status\nEND"]
```

`>>` = human checkpoint (auto-approved when `forge:yolo` label is set)

## Bug Ticket Lifecycle

```mermaid
flowchart TD
    A["Jira ticket created\nforge:managed (Bug)"] --> B[triage_check]
    B -->|missing fields| C[">> triage_gate"]
    C --> B
    B -->|sufficient| D[analyze_bug]
    D --> E["reflect_rca\n(up to 3 cycles)"]
    E --> D
    D --> F[">> rca_option_gate\nuser selects >option N"]
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
    H --> I[qualitative_review]
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
