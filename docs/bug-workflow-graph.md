## Bug Workflow State Machine Diagram & Detail

Below is the detailed, 1:1 code-aligned state machine diagram representing the full Bug Workflow managed in `src/forge/workflow/bug/graph.py`.

```mermaid
flowchart TD
    %% Styling and classes
    classDef planning fill:#E1F5FE,stroke:#01579B,stroke-width:2px;
    classDef execution fill:#E8F5E9,stroke:#1B5E20,stroke-width:2px;
    classDef cicd fill:#FFF3E0,stroke:#E65100,stroke-width:2px;
    classDef human fill:#EDE7F6,stroke:#4A148C,stroke-width:2px;
    classDef qa fill:#FFFDE7,stroke:#F57F17,stroke-width:2px;
    classDef terminal fill:#FFEBEE,stroke:#B71C1C,stroke-width:2px;

    %% Nodes
    route_entry([route_entry]):::planning
    
    %% Triage Phase
    triage_check[triage_check]:::planning
    triage_gate[triage_gate/Pause]:::planning

    %% Analysis + Reflection Phase
    analyze_bug[analyze_bug/Container]:::planning
    reflect_rca[reflect_rca/Container]:::planning
    
    %% RCA Option Gate Phase
    rca_option_gate[rca_option_gate/Pause]:::planning
    regenerate_rca[regenerate_rca]:::planning

    %% Planning Phase
    plan_bug_fix[plan_bug_fix/Container]:::planning
    plan_approval_gate[plan_approval_gate/Pause]:::planning
    regenerate_plan[regenerate_plan]:::planning
    decompose_plan[decompose_plan]:::planning

    %% Q&A Node
    answer_question[answer_question]:::qa

    %% Backward-compat Execution / Implementation Stage
    setup_workspace[setup_workspace]:::execution
    implement_bug_fix[implement_bug_fix/Container]:::execution
    local_review[local_review]:::execution
    update_documentation[update_documentation]:::execution
    create_pr[create_pr]:::execution
    teardown_workspace[teardown_workspace]:::execution

    %% CI/CD Stage
    wait_for_ci_gate[wait_for_ci_gate/Pause]:::cicd
    ci_evaluator[ci_evaluator]:::cicd
    attempt_ci_fix[attempt_ci_fix]:::cicd
    escalate_blocked[escalate_blocked]:::cicd

    %% Review Stage
    human_review_gate[human_review_gate/Pause]:::human
    implement_review[implement_review]:::human
    review_response_gate[review_response_gate]:::human
    
    %% Post-Merge Stage
    post_merge_summary[post_merge_summary]:::human
    
    %% Terminal State
    END_STATE([END]):::terminal

    %% ── Transitions ──
    %% Entry Routing
    route_entry --> triage_check
    route_entry --> triage_gate
    route_entry --> analyze_bug
    route_entry --> reflect_rca
    route_entry --> rca_option_gate
    route_entry --> plan_bug_fix
    route_entry --> plan_approval_gate
    route_entry --> regenerate_plan
    route_entry --> decompose_plan
    route_entry --> setup_workspace
    route_entry --> implement_bug_fix
    route_entry --> local_review
    route_entry --> update_documentation
    route_entry --> create_pr
    route_entry --> teardown_workspace
    route_entry --> wait_for_ci_gate
    route_entry --> ci_evaluator
    route_entry --> human_review_gate
    route_entry --> implement_review
    route_entry --> review_response_gate
    route_entry --> post_merge_summary
    route_entry --> escalate_blocked
    route_entry --> END_STATE

    %% Triage Flow
    triage_check --> _route_after_triage_check{Route}
    _route_after_triage_check -->|triage_check| triage_check
    _route_after_triage_check -->|triage_gate| triage_gate
    _route_after_triage_check -->|analyze_bug| analyze_bug
    _route_after_triage_check -->|escalate_blocked| escalate_blocked

    triage_gate --> route_triage_gate{Route}
    route_triage_gate -->|END| END_STATE
    route_triage_gate -->|triage_check| triage_check

    %% Analysis + Reflection Loop (Self-Correction Loop)
    analyze_bug --> _route_after_analyze_bug{Route}
    _route_after_analyze_bug -->|reflect_rca| reflect_rca
    _route_after_analyze_bug -->|escalate_blocked| escalate_blocked
    _route_after_analyze_bug -->|END| END_STATE

    reflect_rca --> _route_after_reflect_rca{Route}
    _route_after_reflect_rca -->|analyze_bug| analyze_bug
    _route_after_reflect_rca -->|rca_option_gate| rca_option_gate
    _route_after_reflect_rca -->|escalate_blocked| escalate_blocked
    _route_after_reflect_rca -->|END| END_STATE

    %% RCA Option Gate
    rca_option_gate --> route_rca_option{Route}
    route_rca_option -->|plan_bug_fix| plan_bug_fix
    route_rca_option -->|regenerate_rca| regenerate_rca
    route_rca_option -->|answer_question| answer_question
    route_rca_option -->|END| END_STATE

    regenerate_rca --> analyze_bug

    %% Planning Phase
    plan_bug_fix --> _route_after_plan_bug_fix{Route}
    _route_after_plan_bug_fix -->|plan_approval_gate| plan_approval_gate
    _route_after_plan_bug_fix -->|plan_bug_fix| plan_bug_fix
    _route_after_plan_bug_fix -->|escalate_blocked| escalate_blocked
    _route_after_plan_bug_fix -->|END| END_STATE

    plan_approval_gate --> route_plan_approval{Route}
    route_plan_approval -->|decompose_plan| decompose_plan
    route_plan_approval -->|regenerate_plan| regenerate_plan
    route_plan_approval -->|answer_question| answer_question
    route_plan_approval -->|END| END_STATE

    regenerate_plan --> _route_after_regenerate_plan{Route}
    _route_after_regenerate_plan -->|plan_approval_gate| plan_approval_gate
    _route_after_regenerate_plan -->|regenerate_plan| regenerate_plan
    _route_after_regenerate_plan -->|escalate_blocked| escalate_blocked
    _route_after_regenerate_plan -->|END| END_STATE

    decompose_plan --> _route_after_decompose_plan{Route}
    _route_after_decompose_plan -->|setup_workspace| setup_workspace
    _route_after_decompose_plan -->|escalate_blocked| escalate_blocked
    _route_after_decompose_plan -->|END| END_STATE

    %% Q&A Node Routing
    answer_question --> _route_after_answer_bug{Route}
    _route_after_answer_bug -->|triage_gate| triage_gate
    _route_after_answer_bug -->|rca_option_gate| rca_option_gate
    _route_after_answer_bug -->|plan_approval_gate| plan_approval_gate

    %% Backward-compat Execution / Implementation Flow
    setup_workspace --> _route_after_workspace_setup{Route}
    _route_after_workspace_setup -->|implement_bug_fix| implement_bug_fix
    _route_after_workspace_setup -->|escalate_blocked| escalate_blocked

    implement_bug_fix --> _route_after_implementation{Route}
    _route_after_implementation -->|local_review| local_review
    _route_after_implementation -->|implement_bug_fix| implement_bug_fix
    _route_after_implementation -->|escalate_blocked| escalate_blocked

    local_review --> _route_after_local_review{Route}
    _route_after_local_review -->|local_review| local_review
    _route_after_local_review -->|update_documentation| update_documentation
    _route_after_local_review -->|create_pr| create_pr
    _route_after_local_review -->|implement_bug_fix| implement_bug_fix

    update_documentation --> create_pr

    create_pr --> _route_after_pr_creation{Route}
    _route_after_pr_creation -->|teardown_workspace| teardown_workspace
    _route_after_pr_creation -->|escalate_blocked| escalate_blocked

    teardown_workspace --> _route_after_teardown{Route}
    _route_after_teardown -->|setup_workspace| setup_workspace
    _route_after_teardown -->|wait_for_ci_gate| wait_for_ci_gate

    %% CI/CD Flow
    wait_for_ci_gate --> wait_for_ci_gate_route{Route}
    wait_for_ci_gate_route -->|END| END_STATE
    wait_for_ci_gate_route -->|ci_evaluator| ci_evaluator

    ci_evaluator --> _route_ci_evaluation{Route}
    _route_ci_evaluation -->|human_review_gate| human_review_gate
    _route_ci_evaluation -->|attempt_ci_fix| attempt_ci_fix
    _route_ci_evaluation -->|escalate_blocked| escalate_blocked
    _route_ci_evaluation -->|END| END_STATE

    attempt_ci_fix --> attempt_ci_fix_route{Route}
    attempt_ci_fix_route -->|wait_for_ci_gate| wait_for_ci_gate
    attempt_ci_fix_route -->|escalate_blocked| escalate_blocked
    attempt_ci_fix_route -->|ci_evaluator| ci_evaluator

    escalate_blocked --> END_STATE

    %% Review Flow
    human_review_gate --> _route_human_review_bug{Route}
    _route_human_review_bug -->|implement_review| implement_review
    _route_human_review_bug -->|post_merge_summary| post_merge_summary
    _route_human_review_bug -->|complete_tasks| post_merge_summary
    _route_human_review_bug -->|END| END_STATE

    implement_review --> implement_review_route{Route}
    implement_review_route -->|wait_for_ci_gate| wait_for_ci_gate
    implement_review_route -->|review_response_gate| review_response_gate
    implement_review_route -->|implement_review| implement_review
    implement_review_route -->|human_review_gate| human_review_gate
    implement_review_route -->|escalate_blocked| escalate_blocked

    review_response_gate --> route_review_response{Route}
    route_review_response -->|implement_review| implement_review
    route_review_response -->|human_review_gate| human_review_gate
    route_review_response -->|END| END_STATE

    %% Post-Merge State
    post_merge_summary --> END_STATE
```

### Detailed Bug Workflow Phase Summaries & Self-Correction Limits

The Bug Workflow consists of five primary architectural phases plus a legacy execution track to support in-flight runs. Below is the detailed transition logic, inputs, outputs, human-in-the-loop (HITL) gates, error handling, and self-correction mechanics for each group of states.

---

### Phase 1: Triage Phase

The Triage phase is the initial entry point of the Bug Workflow. It evaluates incoming bug reports for completeness and sets up the execution context.

#### State Transitions & Behavior
* **`triage_check`**
  * **Transition Logic**: Automatically initiated upon workflow start or resumption via `route_entry`. Routes to:
    * `analyze_bug`: If the bug report is complete and verified.
    * `triage_gate`: If the ticket lacks sufficient context or detail.
    * `escalate_blocked`: If a critical error or system failure prevents evaluation.
    * `triage_check`: Undergoes a direct retry if designated by the orchestrator.
  * **Inputs**: Raw Jira ticket details (summary, description, metadata), project configurations.
  * **Outputs**: Checklist evaluation results, state context update, target repository resolution, or a detailed error message.
  * **Error Handling**: Missing repository configuration (`MissingProjectConfig`) triggers a Jira comment requesting resolution, labels the ticket as `forge:blocked`, and sets `current_node="triage_check"` for future retry events.

* **`triage_gate`** (Human-in-the-Loop Gate)
  * **Transition Logic**: Once transitioned here, the workflow pauses (`END`) to await human updates to the ticket. When the Jira issue is updated, `route_entry` routes back to `triage_gate` which triggers `route_triage_gate`.
    * If additional updates are still needed, it remains paused (`END`).
    * If the ticket is edited with new details, it transitions to `triage_check` for re-evaluation.
  * **Inputs**: Updated ticket content and status changes.
  * **Outputs**: Refreshed workflow state, Jira label updates (`forge:triage-pending`).
  * **Human-in-the-Loop Gate**: A manual gate requiring the user to add necessary context (e.g. repro steps, logs, or environment details) to the Jira ticket.

---

### Phase 2: Root Cause Analysis (RCA) & Reflection Phase

The RCA & Reflection phase focuses on identifying the root cause of the bug using an autonomous, hypothesis-driven exploration loop inside an isolated container.

#### State Transitions & Behavior
* **`analyze_bug`**
  * **Transition Logic**: Triggered from `triage_check` or looped back from `reflect_rca` or `regenerate_rca`. Routes to:
    * `reflect_rca`: Upon successfully running the analysis and generating the `rca.json` artifact.
    * `escalate_blocked`: If the container runner encounters errors and exceeds the `MAX_ANALYSIS_RETRIES` budget (3 attempts).
    * `END`: For transient execution errors inside the sandbox, terminating the current invocation so a subsequent stream event can retry starting from `analyze_bug` via `route_entry`.
  * **Inputs**: Ticket key, summary, description, target repository credentials, and optional `reflection_critique` from a prior reflection iteration.
  * **Outputs**: `rca_options` (list of 1-4 potential fixes), formatted `rca_content`, `reproducibility_assessment`, and `current_node="reflect_rca"`.
  * **Error Handling & Sandbox Isolation**: Spawns an isolated Podman sandbox container. If the container execution fails (exit code != 0), the handler increments `retry_count`. If `retry_count >= MAX_ANALYSIS_RETRIES` (3), it escalates to `escalate_blocked`.

* **`reflect_rca`** (Autonomous Self-Correction)
  * **Transition Logic**: Routes to:
    * `analyze_bug`: If the reflection agent generates critiques and the iteration cap has not been exceeded.
    * `rca_option_gate`: If the RCA is validated as `"VALID"`, OR if the iteration cap has been reached.
    * `escalate_blocked`: If the reflection container experiences repeated system/runner level exceptions.
    * `END`: On transient execution errors, terminating the invocation to retry later.
  * **Inputs**: Existing `rca_content`, `rca_options`, and loop counters (`reflection_count`).
  * **Outputs**: `reflection_critique` string, updated `reflection_count`, and the selected next state.

#### The RCA Analysis/Reflection Self-Correction Loop Mechanics
To prevent low-quality, erroneous, or hallucinated analyses from reaching humans, the system implements an automated self-critique loop:
1. **Critique Generation**: `reflect_rca` spawns a reflection container using `reflect-rca.md` prompts. This container evaluates the proposed `rca.json` for completeness, evidence quality, and exact code locations.
2. **The 3-Attempt Cap**: The codebase enforces a hard ceiling of exactly 3 reflection attempts using `MAX_REFLECTION_ITERATIONS = 3` (also tracked at the graph file level as `_MAX_REFLECTION_COUNT = 3`).
3. **Loop Mechanics**:
   * **Within Budget (`reflection_count < 3`)**: If the reflection agent issues a critique (non-empty `reflection_critique`), the workflow increments `reflection_count` and routes back to `analyze_bug`. The critique is injected into the prompt of the next analysis container to guide refinement.
   * **Exceeded Budget (`reflection_count >= 3`)**: If the loop reaches 3 iterations without achieving a `"VALID"` verdict, the system halts self-correction. It posts a warning to Jira: `"Reflection cap reached — proceeding with best available RCA after 3 validation attempts."`, updates the state, and transitions straight to `rca_option_gate`.
   * **Successful Validation**: If the reflection container responds with `"VALID"`, the state is cleared (`reflection_critique = None`) and transitions to `rca_option_gate`.

---

### Phase 3: RCA Option Gate Phase

The RCA Option Gate phase acts as the decision point for human operators to select their preferred fix path or request adjustments.

#### State Transitions & Behavior
* **`rca_option_gate`** (Human-in-the-Loop Gate)
  * **Transition Logic**: Uses `route_rca_option` to evaluate the user's action:
    * `plan_bug_fix`: If a valid fix option is approved.
    * `regenerate_rca`: If a revision is requested (prefixed with `!`).
    * `answer_question`: If the user asks a question (prefixed with `?` or `@forge ask`).
    * `END`: Remains paused awaiting input.
  * **Inputs**: Validated RCA details published to Jira, Jira label `forge:rca-pending`, user commands (comments).
  * **Outputs**: User's chosen option, updated labels.
  * **Human-in-the-Loop Gate**: Pauses execution and requires a human interaction on Jira (e.g. comment `>option 1` to choose, or `! Re-analyze...` to revise).

* **`regenerate_rca`**
  * **Transition Logic**: Automatically routes to `analyze_bug` after execution.
  * **Inputs**: User revision request comments, prior workflow state.
  * **Outputs**: Refreshed analysis state, cleared previous options, and injection of user feedback into the new analysis run.

---

### Phase 4: Plan Bug Fix Phase

The Plan Bug Fix phase translates the approved fix option into a detailed implementation design, which undergoes human validation before code implementation begins.

#### State Transitions & Behavior
* **`plan_bug_fix`**
  * **Transition Logic**: Triggered from `rca_option_gate`. Routes to:
    * `plan_approval_gate`: On successful plan generation.
    * `plan_bug_fix` (loop/retry): On transient failure within retry limits.
    * `escalate_blocked`: If failures exceed `_MAX_PLAN_RETRIES` (3).
  * **Inputs**: Chosen RCA option, repository context.
  * **Outputs**: Detailed step-by-step fix plan mapping files, test additions, and execution dependencies.
  * **Error Handling**: Plan generation failures are tracked via `last_error`. Retries are permitted up to 3 times before escalating.

* **`plan_approval_gate`** (Human-in-the-Loop Gate)
  * **Transition Logic**: Uses `route_plan_approval` to route to:
    * `decompose_plan`: If the plan is approved.
    * `regenerate_plan`: If adjustments are requested (prefixed with `!`).
    * `answer_question`: If a user asks a question.
    * `END`: Remains paused awaiting feedback.
  * **Human-in-the-Loop Gate**: Pauses workflow and applies label `forge:plan-pending`. Operators must approve, ask questions, or request adjustments via Jira comment syntax.

* **`regenerate_plan`**
  * **Transition Logic**: Re-runs the planning container with user feedback, then routes to:
    * `plan_approval_gate`: Upon successful update.
    * `regenerate_plan` (retry): In case of failure within retry limits.
    * `escalate_blocked`: If failures exceed 3 attempts.
  * **Inputs**: Prior plan, user adjustments, and feedback.
  * **Outputs**: Updated fix plan.

* **`decompose_plan`**
  * **Transition Logic**: Converts the approved, high-level fix plan into individual repository tasks and routes to:
    * `setup_workspace`: To transition into execution.
    * `escalate_blocked`: In case of formatting or decomposing failures.
  * **Inputs**: Approved fix plan, workspace details.
  * **Outputs**: Target execution files, task structures, and individual repo-specific sub-tasks.

---

### Phase 5: Execution & Verification Phase

The Execution & Verification phase processes the decomposed plan, prepares the development sandboxes, implements code fixes, conducts automated local checks, runs CI/CD validations, and conducts human reviews.

#### State Transitions & Behavior
* **`setup_workspace`**
  * **Transition Logic**: Triggered from `decompose_plan` or `teardown_workspace` (for multi-repo plans). Routes to:
    * `implement_bug_fix`: On successful sandbox and workspace cloning.
    * `escalate_blocked`: On setup or cloning failures (tracked via `last_error`).
  * **Inputs**: Repositories to process, task details.
  * **Outputs**: `workspace_path` populated in state, local workspace prepared.

* **`implement_bug_fix`**
  * **Transition Logic**: Routes to:
    * `local_review`: On successful file modification and local unit tests.
    * `implement_bug_fix` (loop/retry): If transient workspace errors occur within a limit of 3 retries.
    * `escalate_blocked`: Exceeding retry limits under error conditions.
  * **Inputs**: Decomposed tasks, implementation instructions, and local files.
  * **Outputs**: Committed code fixes in the local sandbox workspace, updated file state.

* **`local_review`** (Qualitative Self-Review)
  * **Transition Logic**: Routes to:
    * `update_documentation`: If the implementation passes with an `"adequate"` verdict, or if the review attempt count reaches limits (`_QUALITATIVE_CAP` or `MAX_REVIEW_ATTEMPTS`).
    * `implement_bug_fix`: If tests are marked `"tests_incomplete"` or `"symptom_only"`, prompting the agent to write better tests or fix root causes.
    * `local_review` (retry): On mechanical review failures.
  * **Inputs**: Local git diffs, implementation code, added test cases, and execution logs.
  * **Outputs**: `local_review_verdict` and retry metrics.

* **`update_documentation`**
  * **Transition Logic**: Runs after a successful local review, updating stale markdown or documentation. Leads directly to `create_pr`.
  * **Inputs**: Local diffs, codebase, and docs structure.
  * **Outputs**: Documentation edits committed locally.

* **`create_pr`**
  * **Transition Logic**: Routes to:
    * `teardown_workspace`: On successful PR creation and pushing of local commits.
    * `escalate_blocked`: If the git push or PR creation fails.
  * **Inputs**: Pushed commits, GitHub credentials.
  * **Outputs**: `pr_urls` populated in the state.

* **`teardown_workspace`**
  * **Transition Logic**: Routes to:
    * `setup_workspace`: If other repositories in `repos_to_process` remain outstanding.
    * `wait_for_ci_gate`: If all workspaces are successfully torn down.
  * **Inputs**: Active workspace paths, list of completed repos.
  * **Outputs**: Cleaned filesystem, updated execution tracking.

* **`wait_for_ci_gate`** & **`ci_evaluator`** (Continuous Integration)
  * **Transition Logic**: `wait_for_ci_gate` pauses execution (`END`) until a CI event is triggered. Once triggered, `ci_evaluator` routes to:
    * `human_review_gate`: If CI passes successfully (`ci_status="passed"`).
    * `attempt_ci_fix`: If CI fails (`ci_status="fixing"`).
    * `escalate_blocked`: On critical CI tracking errors.
    * `END`: If CI execution is still pending.
  * **Inputs**: PR status, GitHub Action check run evaluations, CI logs.
  * **Outputs**: `ci_status` metric.

* **`attempt_ci_fix`** (CI Healing Loop)
  * **Transition Logic**: Automatically analyzes remote run logs and attempts code modifications to fix failures. Routes back to `wait_for_ci_gate` on success, or `escalate_blocked` on retry failure.
  * **Inputs**: Detailed failure logs, prior workspace context.
  * **Outputs**: Fix commits pushed to the branch, triggering fresh CI.

* **`human_review_gate`** (Human-in-the-Loop Gate)
  * **Transition Logic**: Routes to:
    * `post_merge_summary`: Intercepted directly if `pr_merged` is `True`.
    * `implement_review`: If review feedback is posted.
    * `END`: Remains paused awaiting reviews.
  * **Human-in-the-Loop Gate**: Requires developers to review the PR, request revisions, or merge it.

* **`post_merge_summary`** (Terminal Transition)
  * **Transition Logic**: Triggered automatically upon PR merge. Generates a summary on Jira, updates the label to completed status, and transitions to `END` to terminate.
  * **Inputs**: Merged branch diffs, commit histories, PR conversations.
  * **Outputs**: Comprehensive final summary comment posted to Jira.

---

### Q&A Handler (`answer_question`)
* **Transition Logic**: Triggered from `triage_gate`, `rca_option_gate`, or `plan_approval_gate` when a user comments with a question (prefixed with `?` or `@forge ask`). After generating the answer, `_route_after_answer_bug` uses `current_node` from the state to route the execution back to the correct originating gate.
* **Inputs**: User's question comment, current workflow step context.
* **Outputs**: Informational answer comment posted directly to Jira.

---

### Rebase Flow (`rebase_pr`)
* **Transition Logic**: Triggered at any stage via the PR comment command `/forge rebase`. Once conflict resolution and rebasing onto main are finished, it reads `current_node` to resume execution at the exact state the workflow was in before rebasing (such as `wait_for_ci_gate`, `human_review_gate`, or `local_review`).
* **Inputs**: Upstream main branch, PR branch, conflict resolution directives.
* **Outputs**: Rebiased PR branch, updated code file state.

---

### Detailed Bug Workflow Stages
