# CLI Reference

Forge provides a command-line interface (CLI) to manage workflows, inspect system health, trigger manual interventions, and view statistics or generate weekly reports.

## Stats Commands

### `forge stats <ticket>`

Display workflow statistics and execution metrics for a specific Jira ticket. This command retrieves the recorded metrics from the Redis checkpoint and formats them for display.

#### Arguments and Flags

| Argument/Flag | Type | Description |
|---|---|---|
| `ticket` | Positional | The Jira ticket key (e.g., `AISOS-123`). This argument is required. |
| `--json` | Flag | Output the raw statistics in JSON format instead of a formatted ASCII table. |

#### Examples

##### 1. Displaying Stats as an ASCII Table

```bash
forge stats AISOS-123
```

**Output:**

```text
================================================================================
Workflow Statistics Summary for AISOS-123
================================================================================
Outcome: Completed

| Stage | Iterations | Machine Time | Input Tokens | Output Tokens | Cost |
|-------|------------|--------------|--------------|---------------|------|
| PRD | 1 | 45s | 12,500 | 4,200 | $0.21 |
| Spec | 1 | 1m 15s | 18,300 | 6,100 | $0.32 |
| Epics | 1 | 30s | 9,800 | 3,100 | $0.16 |
| Tasks | 1 | 25s | 8,500 | 2,800 | $0.14 |
| Implementation | 2 | 4m 10s | 45,000 | 12,500 | $0.78 |
| CI | 2 | 8m 15s | 25,000 | 4,500 | $0.41 |
| Review | 1 | 1m 5s | 15,200 | 4,800 | $0.26 |
|-------|------------|--------------|--------------|---------------|------|
| Total | 9 | 17m 0s | 134,300 | 38,000 | $2.28 |
================================================================================
```

##### 2. Exporting Stats in JSON Format

```bash
forge stats AISOS-123 --json
```

**Output:**

```json
{
  "ticket": "AISOS-123",
  "outcome": "Completed",
  "outcome_detail": null,
  "ci_cycles": 2,
  "pr_urls": [
    "https://github.com/my-org/my-repo/pull/42"
  ],
  "stages": {
    "prd": {
      "stage_name": "prd",
      "iteration_count": 1,
      "machine_time_seconds": 45.0,
      "input_tokens": 12500,
      "output_tokens": 4200
    },
    "spec": {
      "stage_name": "spec",
      "iteration_count": 1,
      "machine_time_seconds": 75.0,
      "input_tokens": 18300,
      "output_tokens": 6100
    },
    "epics": {
      "stage_name": "epics",
      "iteration_count": 1,
      "machine_time_seconds": 30.0,
      "input_tokens": 9800,
      "output_tokens": 3100
    },
    "tasks": {
      "stage_name": "tasks",
      "iteration_count": 1,
      "machine_time_seconds": 25.0,
      "input_tokens": 8500,
      "output_tokens": 2800
    },
    "implementation": {
      "stage_name": "implementation",
      "iteration_count": 2,
      "machine_time_seconds": 250.0,
      "input_tokens": 45000,
      "output_tokens": 12500
    },
    "ci": {
      "stage_name": "ci",
      "iteration_count": 2,
      "machine_time_seconds": 495.0,
      "input_tokens": 25000,
      "output_tokens": 4500
    },
    "review": {
      "stage_name": "review",
      "iteration_count": 1,
      "machine_time_seconds": 65.0,
      "input_tokens": 15200,
      "output_tokens": 4800
    }
  }
}
```

---

## Weekly Reporting Commands

### `forge weekly-report`

Generate a weekly aggregated report of workflow activity and resources consumed across all managed tickets under a specified Jira project.

The report aggregates data across a sliding window of `N` days, detailing completed, in-progress, and blocked workflows, as well as total machine execution time, token usage, and costs.

#### Options and Flags

| Option/Flag | Description |
|---|---|
| `--project PROJECT_KEY` | **Required.** The Jira project key to scope the report (e.g., `PROJ`). |
| `--days N` | The reporting window in days (default: `7`). |
| `--output FILE` | File path to write the report to instead of standard output (`stdout`). |
| `--format FORMAT` | Output format: `text` (default), `markdown`, or `json`. |
| `--create-ticket` | Enable idempotent creation or update of a Jira weekly report issue. The ticket summary follows the pattern `Forge Weekly Report - {PROJECT} - Week of {date}` and carries the `forge:weekly-report` label. Running this command multiple times is idempotent — the existing ticket is updated with the latest content instead of creating duplicates. |
| `--notify` | Post a notification comment on the report ticket mentioning configured stakeholders. Requires `--create-ticket` to have been specified. Stakeholder account IDs are resolved from the per-project Jira property `forge.weekly-report.notify` or the `FORGE_WEEKLY_REPORT_NOTIFY` environment variable. |

#### Examples

##### 1. Generate text report to stdout for the last 7 days

```bash
forge weekly-report --project PROJ
```

##### 2. Generate markdown report for the last 14 days and save it to a file

```bash
forge weekly-report --project PROJ --days 14 --output report.md --format markdown
```

##### 3. Generate report, create/update Jira ticket, and notify stakeholders

```bash
forge weekly-report --project PROJ --create-ticket --notify
```
