# Proposal: Workflow Statistics & Automated Reporting

**Author:** Eran Kuris
**Date:** 2026-05-14
**Status:** Draft

## Summary

When a Forge workflow reaches a terminal state — successful completion, blocked, or unrecoverable failure — the system should automatically post a detailed development statistics summary as a Jira comment on the Feature ticket. Additionally, a weekly status report should aggregate statistics across all active and completed tickets to give stakeholders visibility into cycle times, bottlenecks, and resource consumption. The weekly report is delivered via CLI, email, or Confluence — not on individual Jira tickets.

## Motivation

### Problem Statement

Forge orchestrates the full SDLC — from PRD generation through implementation, CI, and review — but produces no summary of the process once a workflow completes. Teams have no automated way to evaluate how efficiently the pipeline performed:

- Duration of each stage in the workflow.
- Amount of revision cycles prior to approval.
- Token cost of the entire workflow.
- Bottlenecks in the workflow that are repeated across tickets.
- Overall throughput & health of their automated pipeline.

Without this data, stakeholders have no insight into how well the workflow is functioning, and engineers can't identify systemic bottlenecks.

### Current Workarounds

Teams manually correlate Jira comment history and Langfuse traces to recreate timelines. There is no rollup for weekly status. Someone has to manually aggregate tickets together. It's slow and prone to error. 

## Proposal

### Overview

Two complementary features:

1. **Per-ticket summary** — a Jira comment posted automatically when the workflow ends, populated with information about stage durations, number of revisions at each stage, how many tokens were used, links to PRs & CI attempts at fixing them, and rounds of reviews.
2. **Weekly status report** — report aggregating information about all tickets which saw activity during the reporting period. Report sent out as CLI output emailed to users and/or saved to a Confluence page.

Both of these features pull data from LangGraph's checkpoint state, which is augmented with statistic fields that are recorded during execution of the workflow. 

### Detailed Design

#### 1. State Schema: `StatsState` Mixin

A new `StatsState` TypedDict mixin added to `workflow/base.py`, following the existing pattern of `PRIntegrationState`, `CIIntegrationState`, and `ReviewIntegrationState`:

```python
class StatsState(TypedDict, total=False):
    langfuse_trace_id: str | None
    stage_timestamps: dict[str, dict[str, str]]
    gate_timestamps: dict[str, dict[str, str]]
    revision_counts: dict[str, int]
    token_usage: dict[str, int]
    stage_token_usage: dict[str, dict[str, int]]
    review_rounds: int
    workflow_outcome: str | None
```

| Field | Shape | Purpose |
|-------|-------|---------|
| `langfuse_trace_id` | `str` | Links to Langfuse trace for deep observability |
| `stage_timestamps` | `{"prd": {"start": "...", "end": "..."}, ...}` | **Machine time** — duration of active Forge execution (generation, implementation, CI fixes) |
| `gate_timestamps` | `{"prd_approval": {"start": "...", "end": "..."}, ...}` | **Human time** — duration waiting at approval gates and review stages |
| `revision_counts` | `{"prd": 2, "spec": 1, ...}` | Number of regeneration cycles per stage |
| `token_usage` | `{"input": 12345, "output": 6789}` | Aggregate token consumption |
| `stage_token_usage` | `{"prd": {"input": ..., "output": ...}, ...}` | Per-stage token breakdown |
| `review_rounds` | `int` | Number of human review → implement cycles |
| `workflow_outcome` | `"completed" \| "blocked" \| "failed"` | Terminal status for reporting |

**Machine time vs human time:** Each stage tracks two separate durations. Machine time measures how long Forge actively worked (e.g., generating a spec took 12 minutes). Human time measures how long the workflow waited at an approval gate or review stage (e.g., spec approval took 1 day 4 hours). Human time will often greatly exceed machine time. The number of human interactions - requested revisions, review rounds, approval cycles - can act as a proxy for Forge output quality. The fewer revision cycles there are, the better Forge is doing at producing quality artifacts humans can approve rapidly. Monitoring both metrics allows teams to understand not only where their time is going, but if Forge output quality is increasing over time.

`FeatureState` and `BugState` both add `StatsState` to their inheritance chain. `create_initial_feature_state` and `create_initial_bug_state` get default values for all new fields. Both workflow types get identical stats collection and per-ticket summary treatment.

Tracked stages: `prd`, `spec`, `plan`, `task_generation`, `implementation`, `ci`, `review`.
Tracked gates: `prd_approval`, `spec_approval`, `plan_approval`, `task_approval`, `human_review`.

#### 2. Stats Instrumentation

A utility module `workflow/stats/helpers.py` provides four helper functions that nodes call to record data points:

```python
def record_stage_start(state: dict, stage: str) -> dict    # machine time start
def record_stage_end(state: dict, stage: str) -> dict      # machine time end
def record_gate_start(state: dict, gate: str) -> dict      # human wait start
def record_gate_end(state: dict, gate: str) -> dict        # human wait end
def record_tokens(state: dict, stage: str, input_tokens: int, output_tokens: int) -> dict
def increment_revision(state: dict, stage: str) -> dict
```

Each returns the updated state dict with the stats fields modified. Node instrumentation is minimal — one or two calls per node:

| Node | Instrumentation |
|------|----------------|
| `generate_prd` | `record_stage_start("prd")` at entry, `record_stage_end("prd")` + `record_tokens` at completion |
| `regenerate_prd` | `increment_revision("prd")` + `record_tokens` |
| `generate_spec` | `record_stage_start/end("spec")` + `record_tokens` |
| `regenerate_spec` | `increment_revision("spec")` + `record_tokens` |
| `decompose_epics` | `record_stage_start/end("plan")` + `record_tokens` |
| `regenerate_all_epics`, `update_single_epic` | `increment_revision("plan")` + `record_tokens` |
| `generate_tasks` | `record_stage_start/end("task_generation")` + `record_tokens` |
| `implement_task` | `record_stage_start("implementation")` on first task across all repos, `record_stage_end` when the last task in the last repo completes (spans workspace setup/teardown), `record_tokens` per task |
| `evaluate_ci_status`, `attempt_ci_fix` | `record_stage_start/end("ci")` + `record_tokens` |
| `human_review_gate` → review cycle | `record_stage_start/end("review")`, `review_rounds` incremented per cycle |
| `prd_approval_gate` | `record_gate_start("prd_approval")` on pause, `record_gate_end("prd_approval")` on resume |
| `spec_approval_gate` | `record_gate_start("spec_approval")` on pause, `record_gate_end("spec_approval")` on resume |
| `plan_approval_gate` | `record_gate_start("plan_approval")` on pause, `record_gate_end("plan_approval")` on resume |
| `task_approval_gate` | `record_gate_start("task_approval")` on pause, `record_gate_end("task_approval")` on resume |
| `human_review_gate` | `record_gate_start("human_review")` on pause, `record_gate_end("human_review")` on resume |

Token capture: extracted from LLM response objects that already carry `input_tokens` and `output_tokens` metadata. The `langfuse_trace_id` is captured once at the first LLM call and stored in state.

#### 3. Per-Ticket Summary Comment

A new module `workflow/stats/summary.py` with a `post_workflow_summary(state)` function that:

1. Reads stats fields from the checkpoint state
2. Formats a Jira wiki markup comment
3. Posts it to the Feature ticket via `JiraClient.add_comment()`

**Trigger points and summary lifecycle:**

- `escalate_to_blocked` — sets `workflow_outcome = "blocked"` or `"failed"`, calls `post_workflow_summary` with `interim=True`
- `aggregate_feature_status` — sets `workflow_outcome = "completed"`, calls `post_workflow_summary` with `interim=False` (final summary)

**Interim vs final summaries:** When a workflow is blocked or fails, an interim summary is posted immediately, showing all stats accumulated so far. This gives the team context about what happened and where it broke. If the workflow is later resumed via `forge:retry`, stats continue accumulating — they are never reset on retry. When the workflow eventually completes, a final summary is posted covering the entire lifecycle, including time spent blocked and all retry attempts.

The interim summary uses a distinct visual style so it's clearly not the final report:
- Interim: `{panel:title=Forge Workflow Summary (Interim — Blocked)|borderColor=#FF5630}`
- Final: `{panel:title=Forge Workflow Summary|borderStyle=solid}`

**Comment format:**

```
{panel:title=Forge Workflow Summary|borderStyle=solid}

*Outcome:* (/) Completed  |  *Total Duration:* 1d 6h 42m
*Ticket:* PROJ-123  |  *Langfuse Trace:* [View Trace|https://langfuse.example.com/trace/abc123]

h4. Stage Timeline
|| Stage || Machine Time || Human Time || Revisions || Tokens (in/out) ||
| PRD Generation | 8m 12s | 2h 15m | 0 | 2,340 / 1,890 |
| Spec Generation | 12m 04s | 1d 4h 10m | 1 | 4,120 / 3,450 |
| Epic Decomposition | 6m 30s | 45m | 0 | 3,200 / 2,800 |
| Task Generation | 4m 15s | 30m | 0 | 1,800 / 1,200 |
| Implementation | 2h 45m | — | — | 18,500 / 12,300 |
| CI Validation | 18m 20s | — | — | 1,200 / 900 |
| Human Review | — | 8m 00s | — | — |

h4. Execution Details
* *PRs Created:* [PR #42|https://github.com/...], [PR #43|https://github.com/...]
* *CI Fix Attempts:* 1
* *Review Rounds:* 2
* *Tasks Completed:* 5/5
* *Total Machine Time:* 3h 34m
* *Total Human Time:* 1d 3h 08m
* *Total Tokens:* 31,160 input / 22,540 output

{panel}
```

Stages that were never reached (e.g., Human Review on a blocked ticket) show "—" for all columns. This makes it immediately clear where the workflow stopped.

For blocked or failed outcomes, the header shows `(x) Blocked` or `(x) Failed` with the `last_error` message included.

#### 4. Weekly Status Report

A new module `workflow/stats/weekly_report.py` that aggregates data across all checkpoints with activity in the reporting window.

**Data collection:** Scans all LangGraph checkpoints in Redis using existing `list_checkpoints` + `get_checkpoint_state` helpers. For each checkpoint, includes it if any `stage_timestamps` entry or `updated_at` falls within the reporting window.

**Report structure:**

| Section | Content |
|---------|---------|
| Summary | Ticket counts by status, total tokens, avg cycle time |
| Completed Tickets | Per-ticket row: key, title, duration, tokens, revisions |
| In Progress | Per-ticket row: key, title, current stage, elapsed time |
| Blocked | Per-ticket row: key, title, blocked stage, duration, error summary |
| Bottleneck Analysis | Slowest machine stage avg, longest human wait avg, most revised stage, CI first-pass rate |
| Token Consumption | Totals and percentage breakdown by stage |

#### 5. Weekly Report Delivery

Three output targets from a single report engine:

**CLI (default):**
```bash
forge weekly-report                                # stdout, last 7 days
forge weekly-report --days 14                      # custom window
forge weekly-report --output report.md             # file export
forge weekly-report --format json --output r.json  # JSON for tooling
```

**Email:**
```bash
forge weekly-report --email                        # configured recipients
forge weekly-report --email --to "mgr@company.com" # override recipients
```

- Recipients configured via `FORGE_REPORT_EMAIL_TO` env var or project settings
- Email delivery via Gmail SMTP (`smtp.gmail.com`) or the Gmail API
- HTML-formatted email matching the CLI report content

**Confluence:**
```bash
forge weekly-report --confluence                                    # defaults
forge weekly-report --confluence --space TEAM --parent "Weekly Reports" # explicit
```

- Creates a new page per reporting window under a configured parent page
- Page title: `Forge Weekly Report — YYYY-MM-DD to YYYY-MM-DD`
- Idempotent: updates the page if it already exists for the same window
- Includes historical week-over-week trend charts:
  - **Cycle time trend** — avg total machine time and human time per completed ticket, week over week
  - **Token consumption trend** — total input/output tokens per week
  - **Revision rate trend** — avg revision count per stage across completed tickets
  - **Throughput trend** — number of tickets completed, blocked, and in-progress per week
  - **CI fix rate trend** — percentage of tickets passing CI on first attempt
  - Charts rendered as Confluence chart macros (bar/line charts using the built-in Chart macro) sourced from a data table on the same page. Each weekly report appends its data row to the table, building the historical view incrementally.
- New `integrations/confluence/client.py` using the Confluence REST API

Flags can be combined: `forge weekly-report --email --confluence` sends email and updates Confluence in one run.

Scheduling is external — any cron job or CI pipeline can invoke the CLI command on a weekly cadence.

### User Experience

**Per-ticket summary — automatic, no user action required:**

When a workflow completes (or is blocked/fails), the team sees a structured summary comment appear on the Jira ticket. Engineers and managers can review cycle times, identify which stages required revisions, and click through to the Langfuse trace for deep observability.

**Weekly report — on-demand or scheduled:**

```bash
# Team lead runs it Monday morning
$ forge weekly-report

== Forge Weekly Status Report ==
Period: 2026-05-07 → 2026-05-14

SUMMARY
  Completed: 4 tickets  |  In Progress: 3  |  Blocked: 1
  Total tokens: 245,800 in / 178,200 out
  Avg. cycle time (completed): 4h 12m

COMPLETED TICKETS
  PROJ-101  Feature X         3h 42m   31k tokens   0 revisions
  PROJ-108  Feature Y         5h 10m   48k tokens   2 revisions
  PROJ-112  Bug Z             1h 05m   12k tokens   0 revisions
  PROJ-115  Feature W         6h 50m   52k tokens   1 revision

IN PROGRESS
  PROJ-120  Feature A         at: Implementation    elapsed: 2h 30m
  PROJ-122  Feature B         at: Spec Approval     elapsed: 1d 4h
  PROJ-125  Bug C             at: CI Validation     elapsed: 45m

BLOCKED
  PROJ-118  Feature D         at: CI Validation     blocked: 2d
  → CI fixes exhausted after 5 attempts (lint-check, type-check)

BOTTLENECK ANALYSIS
  Slowest machine stage (avg): Implementation — 2h 48m avg across 4 tickets
  Longest human wait (avg): Spec Approval — 1d 2h avg
  Most revised stage: Spec — 1.5 avg revisions
  CI fix rate: 3/4 tickets passed CI on first attempt

TOKEN CONSUMPTION
  Total: 245,800 in / 178,200 out
  By stage: Implementation 62% | Spec 14% | PRD 10% | Plan 8% | Other 6%

# Or auto-deliver every Monday
$ crontab -e
0 9 * * 1 forge weekly-report --email --confluence
```

## Alternatives Considered

| Alternative | Pros | Cons | Why Not |
|-------------|------|------|---------|
| Query Langfuse for all stats at report time | Keeps checkpoint state lean; Langfuse already has token data | Adds external API dependency during reporting; stage durations not tracked in Langfuse; weekly aggregation requires many API calls | Self-contained checkpoint data is simpler and more reliable |
| Persist stats to a separate Redis store | Decouples reporting from workflow state; flexible schema | Two sources of truth; extra write path; must keep in sync with checkpoint | Unnecessary complexity when checkpoint already persists per-node |
| LangGraph callback middleware for auto-instrumentation | Nodes stay untouched; new nodes auto-tracked | LangGraph node-level callback API is limited; token usage happens inside nodes, not at graph level; adds indirection | Still requires per-node token capture; net-more complex |
| Decorator-based `@track_stage` on node functions | Clean separation of concerns; explicit opt-in | Async decorator + TypedDict state interaction is fragile; still need token passthrough | Pragmatically harder than inline calls for marginal benefit |
| Post weekly report as Jira comments on tickets | All data in one place | Floods individual tickets with aggregate data irrelevant to that ticket; managers must still visit each ticket | Weekly report is for managers, not per-ticket context |

## Implementation Plan

### Phases

1. **Phase 1: State schema + helpers** — Add `StatsState` mixin, implement `workflow/stats/helpers.py`, add defaults to initial state functions. (~0.5 day)
2. **Phase 2: Node instrumentation** — Add `record_stage_start/end`, `record_tokens`, `increment_revision` calls to all generation, regeneration, implementation, CI, and review nodes. (~1 day)
3. **Phase 3: Per-ticket summary** — Implement `workflow/stats/summary.py`, wire into `aggregate_feature_status` and `escalate_to_blocked`, format Jira comment. (~0.5 day)
4. **Phase 4: Weekly report engine** — Implement `workflow/stats/weekly_report.py` with checkpoint scanning, aggregation, and report formatting. (~1 day)
5. **Phase 5: CLI command** — Add `forge weekly-report` subcommand with `--days`, `--output`, `--format` flags. (~0.5 day)
6. **Phase 6: Email delivery** — Implement `integrations/email/client.py`, add `--email`/`--to` flags, SMTP configuration. (~0.5 day)
7. **Phase 7: Confluence delivery** — Implement `integrations/confluence/client.py`, add `--confluence`/`--space`/`--parent` flags. (~1 day)
8. **Phase 8: Tests** — Unit tests for helpers, summary formatting, report aggregation. Integration tests for CLI command. (~1 day)

### Dependencies

- [ ] LLM response objects must expose `input_tokens` / `output_tokens` (already available via Anthropic API responses)
- [ ] Redis checkpointer must support scanning all checkpoints (existing `list_checkpoints` helper)
- [ ] Confluence REST API credentials for Phase 7 (`FORGE_CONFLUENCE_URL`, `FORGE_CONFLUENCE_TOKEN`)
- [ ] Gmail SMTP credentials for Phase 6 (`FORGE_GMAIL_USER`, `FORGE_GMAIL_APP_PASSWORD`, `FORGE_REPORT_EMAIL_FROM`)

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Token usage not consistently available from all LLM call paths (direct API vs agent vs container) | Med | Med | Audit all LLM invocation paths in Phase 2; use 0 as fallback for paths that don't expose usage |
| Checkpoint scanning for weekly report is slow with many tickets | Low | Med | `list_checkpoints` already limits results; add date-based filtering to avoid scanning old checkpoints |
| Stats fields increase checkpoint size in Redis | Low | Low | Fields are small (timestamps, integers); negligible compared to existing `messages` and `context` fields |
| Confluence API rate limits on large report updates | Low | Low | Reports are small documents; single create/update call per week |

## Open Questions

- [ ] For token usage in containerized implementation (Deep Agents), can we extract usage from the agent's response, or do we need to query Langfuse for that specific trace?

## References

- Design draft: `docs/superpowers/specs/2026-05-13-workflow-stats-reporting-design.md`
- Existing Prometheus metrics: `src/forge/api/routes/metrics.py`
- Langfuse tracing integration: `src/forge/integrations/langfuse/tracing.py`
- LangGraph checkpoint system: `src/forge/orchestrator/checkpointer.py`
- Workflow terminal nodes: `src/forge/workflow/nodes/human_review.py`
- Related proposal: [PR #31](https://github.com/forge-sdlc/forge/pull/31) — Revision Summary on Artifact Approval (covers per-stage revision history posted on approval; this proposal tracks revision counts as part of broader workflow stats, not as standalone approval-time summaries)
