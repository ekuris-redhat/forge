<p align="center">
  <img src="docs/images/logo.png" alt="Forge Logo" width="1000">
</p>

<p align="center">
  <a href="https://github.com/Forge-sdlc/forge/actions/workflows/ci.yml">
    <img alt="CI" src="https://github.com/Forge-sdlc/forge/actions/workflows/ci.yml/badge.svg">
  </a>
  <a href="https://github.com/Forge-sdlc/forge/actions/workflows/docs.yml">
    <img alt="Docs" src="https://github.com/Forge-sdlc/forge/actions/workflows/docs.yml/badge.svg">
  </a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-green">
</p>

<p align="center">
  <img alt="Jira Ticket" src="https://img.shields.io/badge/Jira-Ticket-0052CC">
  <img alt="AI Planning" src="https://img.shields.io/badge/AI-Planning-7C3AED">
  <img alt="Containerized Code" src="https://img.shields.io/badge/Code-Containerized-2496ED">
  <img alt="GitHub PR" src="https://img.shields.io/badge/GitHub-PR-181717">
  <img alt="CI Repair" src="https://img.shields.io/badge/CI-Auto--repair-F97316">
  <img alt="Human Review" src="https://img.shields.io/badge/Human-Review-16A34A">
</p>

# Forge

Forge turns Jira tickets into reviewed GitHub pull requests.

It plans work, asks for human approval, implements changes in isolated containers, opens PRs, fixes CI failures, and pauses for review before anything is merged. Forge is built for teams that want AI to participate in the software delivery lifecycle without bypassing the controls that make engineering work trustworthy.

Forge is for work that cannot be handled by a single prompt: cross-repo changes, approval gates, CI failures, review feedback, audit trails, and project-level visibility.

<p align="center">
  🎫 <strong>Jira ticket</strong> → 🧭 <strong>Human-gated plan</strong> → 📦 <strong>Repo-scoped implementation</strong> → 🔀 <strong>GitHub PRs</strong> → 🛠️ <strong>CI repair</strong> → 👀 <strong>Human review</strong> → 📊 <strong>Summary + dashboards</strong>
</p>

## What Forge Does

Forge connects Jira, GitHub, and AI coding agents into one event-driven workflow:

- **Turns product intent into implementation plans**: Generate PRDs, behavioral specs, epics, tasks, RCA reports, and concrete fix plans from Jira issues.
- **Plans across repositories**: Decompose features and bugs across the repositories configured for a Jira project, then create repo-scoped epics, tasks, implementation passes, and PRs.
- **Keeps humans in the loop**: Pause at approval gates, answer reviewer questions, regenerate artifacts from feedback, and require human PR review before merge.
- **Implements code in controlled environments**: Run implementation inside ephemeral Podman containers with repository access scoped to the task.
- **Handles the PR lifecycle**: Create fork-based PRs, write PR descriptions, respond to review feedback, rebase when needed, and keep Jira updated.
- **Repairs failing CI**: Analyze failing checks, apply fixes, push updates, and retry until the workflow is ready for review or blocked with a clear reason.
- **Adapts to each project**: Use skills to customize how Forge writes plans, implements code, reasons about CI, and follows team conventions.

## Model Backends

Forge is built on [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview) and passes agents a LangChain chat model instance.

The built-in model factory supports direct Anthropic API credentials and Google Vertex AI-backed models. Because the agent layer is model-object based, Forge can be extended to any LangChain-compatible chat model by adding it to the model factory.

## Where Forge Is Different

Forge is not just an agent with a large prompt or a folder of skills. It is a stateful delivery workflow that decides what should happen next, when to pause, which artifact needs review, which repository should be changed, and how to recover when something fails.

- **Workflow first, agents second**: LangGraph coordinates the lifecycle from ticket intake to PR review. Agents perform bounded stage work; the workflow owns routing, checkpoints, retries, approvals, and handoffs.
- **Cross-repo by design**: Forge can plan features and bugs across services, clients, infrastructure, and documentation repos, then split the work into repo-scoped units that can be implemented and reviewed independently.
- **Controlled write boundaries**: Agents do not directly mutate Jira, GitHub, or production repositories. Implementation agents write only inside their local/container workspace; Forge's integration layer performs external updates such as Jira comments, labels, branch pushes, and PR creation at explicit workflow steps.
- **Native engineering loop**: Forge works through Jira tickets, Jira comments, Jira labels, GitHub PRs, GitHub reviews, and CI webhooks instead of forcing teams into a separate agent UI.
- **Traceable by default**: Work is reflected back into Jira and GitHub as comments, labels, PRs, review updates, CI decisions, and post-merge summaries, so teams can follow why the workflow moved or paused.
- **Project visibility**: Prometheus metrics, Langfuse traces, and Grafana dashboards expose workflow throughput, step latency, ticket execution cost, model usage, CI behavior, and observability health by project, ticket type, workflow step, and Jira issue.
- **Evidence-backed bug fixing**: Bug workflows include triage, codebase investigation, RCA validation, fix-option selection, plan approval, implementation, qualitative review, and post-merge summaries.
- **Bounded autonomy**: Forge can move quickly, but approval gates, review gates, retry budgets, blocked states, and audit comments keep the system inspectable.

## Why Forge

Most AI coding tools start at the editor. Forge starts at the ticket.

That changes the shape of the work. Instead of asking a coding agent to make an isolated change, Forge manages the path from request to reviewed pull request:

1. Understand the issue.
2. Produce the right planning artifact.
3. Ask for approval or clarification.
4. Decompose the work into repo-scoped executable tasks.
5. Implement and review the code.
6. Open a pull request.
7. Watch CI and fix failures.
8. Wait for human review.
9. Report the outcome back to Jira.

The goal is not to remove engineering judgment. The goal is to give engineering teams an automated delivery loop where judgment is applied at explicit checkpoints.

Forge also makes the delivery loop observable. Teams can inspect individual ticket execution in Jira, GitHub, Langfuse, and Grafana, while project dashboards show where work is flowing, where it is blocked, how much CI repair is happening, and which workflow stages cost the most time or model budget.

## Workflows

### Feature Workflow

Forge can take a Jira Feature from idea to one or more pull requests:

```text
Feature Ticket
  -> PRD
  -> Behavioral Spec
  -> Cross-repo Epics
  -> Repo-scoped Implementation Tasks
  -> Containerized Implementation
  -> Local AI Review
  -> GitHub PRs
  -> CI Fix Loop
  -> AI Review
  -> Human Review
```

## Quick Start

### 1. Prerequisites

- Python 3.11+
- Redis Stack (includes RediSearch module)
- Podman (for code execution containers)
- Jira Cloud account with API access
- GitHub account with Personal Access Token
- Anthropic API key (or Google Vertex AI)

### 2. Installation

```bash
# Clone and install
git clone https://github.com/your-org/forge.git
cd forge
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your credentials (see Configuration section)

# Build the container image
podman build -t forge-dev:latest -f containers/Containerfile containers/
```

### 3. Start Services

```bash
# Terminal 1 — Redis (the only service that runs in Docker)
docker compose up redis -d

# Terminal 2 — API server
uv run uvicorn forge.main:app --reload --port 8000 --host 0.0.0.0

# Terminal 3 — Worker (must run on the host — it spawns Podman containers)
uv run forge worker
```

### 4. Configure Webhooks

Set up webhooks in Jira and GitHub pointing to your server:

**Jira Webhook:**
- URL: `https://your-server.com/api/v1/webhooks/jira`
- Events: Issue created, updated, commented

**GitHub Webhook:**
- URL: `https://your-server.com/api/v1/webhooks/github`
- Events: Pull requests, Pull request reviews, Check runs, Issue comments


## Usage

### Starting a Feature Workflow

1. **Create a Jira Feature** with the label `forge:managed`
2. Forge automatically generates a PRD and posts it to the ticket
3. **Review and approve** by changing the label to `forge:prd-approved`
4. Forge generates a behavioral specification
5. Continue approving through Spec → Epics → Tasks → Implementation

### Workflow Labels

Use these labels in Jira to control the workflow:

| Stage | Pending Label | Approved Label |
|-------|--------------|----------------|
| PRD | `forge:prd-pending` | `forge:prd-approved` |
| Spec | `forge:spec-pending` | `forge:spec-approved` |
| Plan | `forge:plan-pending` | `forge:plan-approved` |
| Tasks | `forge:task-pending` | `forge:task-approved` |

### Autonomous Mode (`forge:yolo`)

> **⚠️ Warning:** Adding `forge:yolo` to a ticket removes all human approval checkpoints for planning artifacts. Forge will proceed from ticket creation straight through to implementation without pausing at the PRD, spec, plan, or task gates. Use this only when you trust the requirements and are comfortable with Forge making all planning decisions autonomously.

Add `forge:yolo` to a ticket to enable autonomous mode:
- Forge skips the PRD, spec, plan, and task approval gates
- In the bug workflow, Forge auto-selects RCA option 1
- **The code review gate is never skipped** — a human reviewer is always required on the implementation PR
- `forge:yolo` can be added at ticket creation or while the workflow is already paused at a gate — Forge will immediately advance

### Jira Comment Syntax

Forge classifies Jira comments by their prefix:

| Prefix | Type | What happens |
|--------|------|--------------|
| `!` | Revision request | Forge regenerates the current artifact with your feedback |
| `?` or `@forge ask` | Question | Forge answers without advancing or regenerating |
| `>option N` | RCA option selection | Selects a fix option (RCA Option Gate only) |
| `/forge stats` | Stats request | Forge posts current workflow statistics as a comment |
| `/forge stats retry` | Stats refresh | Re-posts stats comment with fresh data |
| _(no prefix)_ | Informational | Ignored by the workflow |

### Requesting Revisions

Start your comment with `!` followed by your feedback. Forge will regenerate the current artifact incorporating your feedback.

```
! The PRD is missing non-functional requirements for latency
```

### Asking Questions (Q&A Mode)

While reviewing a PRD or Spec, you can ask clarifying questions without triggering regeneration:

- Start your comment with `?` — e.g., `? Why did you choose REST over GraphQL?`
- Or use `@forge ask` — e.g., `@forge ask explain the auth approach`

Forge will answer based on the artifact content and generation context, then keep the workflow paused for your approval decision. When you approve, a summary of Q&A exchanges is posted to the ticket for future reference.

!!! note
    Comments without a recognized prefix (`!`, `?`, `@forge ask`, `>option`) are treated as informational and do not trigger any workflow action.

### Handling Failures

When a workflow fails:
1. Forge sets the `forge:blocked` label
2. Forge posts a comment tagging the reporter and assignee
3. To retry: Add the `forge:retry` label — Forge resumes from the exact node that failed, not from the beginning

> **CI-specific:** If CI fix attempts are exhausted, adding `forge:retry` resets the attempt counter so Forge gets a fresh budget of retries.

### Skipping CI Gates

When a CI check fails due to infrastructure issues unrelated to your code (e.g. a cloud environment outage, quota exhaustion, or a flaky test runner), you can bypass it with a PR comment:

```
/forge skip-gate <check-name-substring>
```

**Examples:**
```
/forge skip-gate e2e-openstack-ovn
/forge skip-gate e2e-openstack        ← skips all checks containing this substring
```

Forge will:
1. Reply on the PR confirming the skip
2. Post an audit comment on the Jira ticket
3. Re-evaluate CI treating the skipped check as passing

To remove a skip:
```
/forge unskip-gate e2e-openstack-ovn
```

Skips persist across pushes — if the infra check fails again on the next commit, it is still skipped. The check name is matched as a case-insensitive substring of the full check name.

> **Note:** Certain checks (e.g. `tide`, Prow's merge-queue) are always pending and are permanently ignored. Configure with `CI_IGNORED_CHECKS` in `.env`.

### Resolving Merge Conflicts

When a PR falls behind `main` and develops merge conflicts, post a comment:

```
/forge rebase
```

Forge merges `main` into the PR branch, resolving any conflicts using AI. If the merge is clean, it pushes immediately. If there are conflicts, a container with Claude resolves them using the PR description as context, then force-pushes to the fork. This works from any workflow stage.

See [PR Commands](docs/guide/pr-commands.md) for the full reference.

### Bug Workflow

Forge can take a Jira Bug through diagnosis, planning, implementation, and post-merge reporting:

```text
Bug Ticket
  -> Triage
  -> Root Cause Analysis
  -> Fix Options
  -> Plan Approval
  -> Repo-scoped Implementation Tasks
  -> Fix PRs
  -> CI + Review
  -> Post-merge Summary
```

For bugs, Forge investigates the codebase, proposes concrete fix options, waits for an option selection, implements the chosen approach across the affected repos, and posts a summary after merge.

## Human Control

Forge is designed around approval gates, auditability, and recoverability:

- **Approval gates** before major planning transitions.
- **Q&A mode** for asking questions about generated artifacts before approving.
- **Revision requests** for regenerating artifacts with human feedback.
- **Containerized implementation** so coding work happens in isolated task environments.
- **Controlled external writes** so agents work locally while Forge performs Jira/GitHub mutations through explicit workflow steps.
- **Local review before PR creation** to catch obvious issues before reviewers see them.
- **CI repair loop** with bounded retry attempts and clear blocked states.
- **Human PR review** before merge, even when autonomous mode is enabled.
- **Resumable workflows** that checkpoint state and resume from the failed node.
- **Operational dashboards** for tracking workflow health, ticket execution, model usage, and project-level delivery trends.

Forge can run with more automation when a ticket is trusted, but the final code review gate remains a human checkpoint.

## Customization

Forge uses skills to adapt agent behavior to your project.

Skills are Markdown instruction files that define how Forge should produce PRDs, specs, implementation plans, code changes, CI analysis, and review feedback. They customize stages inside the workflow; they do not replace the workflow itself. Teams can keep shared defaults while overriding only the parts that are specific to a stack, repository, or Jira project.

This lets Forge follow local engineering conventions without forking the orchestrator.

## Architecture

Forge is event-driven:

```text
Jira + GitHub Webhooks
  -> FastAPI Gateway
  -> Redis Streams Queue
  -> LangGraph Workflow
  -> Host Orchestrator Agent
  -> Container Agent for Implementation
  -> Jira + GitHub Updates
```

Jira and GitHub send webhooks to Forge. Forge queues events, resumes the right workflow state, runs the next node, and posts the result back to Jira or GitHub. Planning runs through the host orchestrator. Code implementation runs in short-lived containers. Agents generate artifacts and local code changes; Forge's workflow and integration layer decide when those outputs become Jira updates, branch pushes, or pull requests.

## Documentation

- [Getting Started](https://Forge-sdlc.github.io/forge/getting-started/): Install Forge and run your first workflow.
- [Feature Workflow](https://Forge-sdlc.github.io/forge/guide/feature-workflow/): Understand the feature pipeline and approval gates.
- [Bug Workflow](https://Forge-sdlc.github.io/forge/guide/bug-workflow/): Understand triage, RCA, fix options, and bug implementation.
- [PR Commands](https://Forge-sdlc.github.io/forge/guide/pr-commands/): Rebase PRs and handle CI gate skips.
- [Configuration Reference](https://Forge-sdlc.github.io/forge/reference/config/): Environment variables and project configuration.
- [Skills System](https://Forge-sdlc.github.io/forge/skills/): Customize Forge for your team and stack.
- [Developer Guide](https://Forge-sdlc.github.io/forge/developer-guide/): Local testing, debugging, Prometheus metrics, Langfuse tracing, and Grafana dashboards.

## Contributing

The most useful way to extend Forge is to teach it how your team works.

Contributions can improve the orchestrator, workflow stages, integrations, or default skills. Teams can also publish project-specific skill sets that customize planning, implementation, CI behavior, and review conventions.

See [Contributing](https://Forge-sdlc.github.io/forge/dev/contributing/) for the full guide.
