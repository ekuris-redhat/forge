# Weekly Reporting System

Forge includes an automated, weekly aggregation and reporting system that compiles and publishes metrics across all managed tickets for a specific Jira project. This documentation explains how the reporting system operates behind the scenes.

## Aggregation Logic

When you run `forge weekly-report` (or trigger it via automated schedules), the reporting system performs the following steps:

1. **Query Active/Historical Checkpoints:** Forge scans the Redis event and state checkpoints for the specified project (`PROJECT_KEY`). It uses a key scanning pattern `langgraph:checkpoint:{PROJECT_KEY}-*` to find all state checkpoints.
2. **Filter by Sliding Window:** Metrics are collected and filtered based on a sliding window of `N` days (by default, `7` days). A checkpoint falls within the reporting window if its `updated_at` timestamp or any stage `started_at`/`ended_at` timestamp is greater than or equal to the cutoff (`now - N days`).
3. **Aggregate Stats per Stage:** Data is aggregated across all feature and bug workflows, tracking:
   - **Ticket Rollups:** Total numbers of active, completed, or blocked workflows.
   - **Machine Time:** Cumulative active machine processing time (monotonic durations) across all stages.
   - **LLM Token Costs:** Sum of all input and output tokens consumed, translating them into actual dollar costs based on LLM pricing mappings.
   - **Feature Rollups:** Metrics aggregated per epic-linked ticket and feature. Ancestry traversal resolves the parent/grandparent Feature for each ticket in Jira up to two hops (e.g., ticket -> Epic -> Feature). Tickets without a resolved Feature are grouped under the "Unassigned" bucket.
   - **Bottleneck Analysis:** Identifies the slowest stage by average duration, ranks stages by iteration count, and calculates the CI fix rate.

## Idempotency & Ticket Publishing

To avoid cluttering Jira with duplicate reports every week, the reporting system is designed to be completely **idempotent** when publishing to Jira via the `--create-ticket` flag.

- **Ticket Naming Convention:** The ticket summary is formatted dynamically based on the project key and current date:
  ```text
  Forge Weekly Report - {PROJECT} - Week of {date}
  ```
  Where `{PROJECT}` is the project key, and `{date}` is the first day of the reporting week (i.e. `today - N + 1 days`).
- **Label Identification:** The system uses the special `forge:weekly-report` and `forge:generated` labels to identify and tag report tickets.
- **Idempotency Guard:**
  - When `--create-ticket` is run, Forge first searches Jira using the following JQL:
    ```jql
    project = "{PROJECT}" AND labels = "forge:weekly-report" AND summary ~ "Week of {date}"
    ```
  - If a matching ticket is found, Forge updates that existing ticket's description with the newly compiled statistics instead of creating a new one.
  - If no matching ticket exists, Forge creates a new Jira Task issue, assigns the `forge:weekly-report` and `forge:generated` labels, and sets the description.

## Stakeholder Notifications

When using the `--notify` option alongside `--create-ticket`, Forge automatically mentions and notifies designated stakeholders.

### Notification List Compilation

The notification list is compiled hierarchically to allow easy overriding (highest priority first):

1. **Jira Project Property (Highest Priority):** Forge attempts to read the `forge.weekly-report.notify` project property from Jira. This property must contain a JSON array of Jira Account IDs (e.g., `["account-id-1", "account-id-2"]`) or a comma-separated string of account IDs.
2. **Environment Variable (Global Fallback):** If no project-specific property is set, Forge falls back to the `FORGE_WEEKLY_REPORT_NOTIFY` environment variable in `.env`. This variable should contain a comma-separated list of Jira Account IDs or the keyword `"project-leads"`. The special value `"project-leads"` instructs Forge to query the per-project Jira property.
3. **No Recipients:** If neither is configured, no notifications are triggered.

### How Notifications are Delivered

Once the recipient account IDs are resolved:
- Forge posts a comment directly on the generated weekly report Jira ticket.
- The comment mentions each stakeholder using Jira's native `[~accountid:{id}]` mention syntax.
- This triggers email and/or Slack notifications based on the users' individual Atlassian notification preferences, ensuring visibility to project leads and management.
