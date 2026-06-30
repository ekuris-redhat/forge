# Configuration

All configuration is via environment variables in `.env`. See `.env.example` in the repository for the complete list with comments.

## Required Variables

### Jira

| Variable | Description |
|----------|-------------|
| `JIRA_BASE_URL` | Your Atlassian instance URL (e.g., `https://your-org.atlassian.net`) |
| `JIRA_USER_EMAIL` | Service account email |
| `JIRA_API_TOKEN` | Jira API token |
| `JIRA_WEBHOOK_SECRET` | Secret for validating Jira webhook signatures |

### GitHub

| Variable | Description |
|----------|-------------|
| `GITHUB_TOKEN` | Personal Access Token with `repo` and `read:org` scopes |
| `GITHUB_WEBHOOK_SECRET` | Secret for validating GitHub webhook signatures |

### LLM

Choose one backend:

=== "Anthropic Direct"

    ```bash
    ANTHROPIC_API_KEY=sk-ant-your-key
    LLM_MODEL=claude-opus-4-5@20251101
    ```

=== "Google Vertex AI"

    ```bash
    ANTHROPIC_VERTEX_PROJECT_ID=your-gcp-project
    ANTHROPIC_VERTEX_REGION=us-east5
    LLM_MODEL=claude-opus-4-5@20251101
    ```

### Redis

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6380/0` | Redis connection URL |

## Per-Project Repository Configuration

!!! warning "Production requirement"
    In production, Forge reads repository configuration from Jira project properties, **not** from environment variables. If not configured, Forge blocks the workflow and posts setup instructions on the ticket.

Set these properties per Jira project via the REST API:

```bash
# Available repos for this project
curl -X PUT \
  "https://your-org.atlassian.net/rest/api/3/project/MYPROJ/properties/forge.repos" \
  -H "Content-Type: application/json" \
  -u "you@example.com:YOUR_API_TOKEN" \
  -d '["org/repo1", "org/repo2"]'

# Default repo when no explicit assignment is made
curl -X PUT \
  "https://your-org.atlassian.net/rest/api/3/project/MYPROJ/properties/forge.default_repo" \
  -H "Content-Type: application/json" \
  -u "you@example.com:YOUR_API_TOKEN" \
  -d '"org/repo1"'
```

## Local Development Overrides

Use these to skip the Jira project property requirement during local development:

| Variable | Description |
|----------|-------------|
| `FORGE_REQUIRE_PROJECT_CONFIG` | Set to `false` to use env var fallbacks instead of Jira project properties |
| `GITHUB_DEFAULT_REPO` | Default repo (`org/repo`) when `FORGE_REQUIRE_PROJECT_CONFIG=false` |
| `GITHUB_KNOWN_REPOS` | Comma-separated list of known repos |

## CI and Validation

| Variable | Description |
|----------|-------------|
| `CI_IGNORED_CHECKS` | Comma-separated list of check name substrings to permanently ignore (e.g., `tide,queue`) |
| `CI_MAX_FIX_ATTEMPTS` | Maximum CI fix attempts before blocking (default: `5`) |

## Container Execution

| Variable | Description |
|----------|-------------|
| `CONTAINER_IMAGE` | Container image for task execution (default: `forge-dev:latest`) |
| `CONTAINER_MEMORY_LIMIT` | Memory limit for task containers (default: `4g`) |
| `CONTAINER_CPU_LIMIT` | CPU limit for task containers (default: `2`) |

## Observability

### Langfuse Tracing

| Variable | Description |
|----------|-------------|
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key |
| `LANGFUSE_HOST` | Langfuse host (defaults to cloud; set for self-hosted) |
| `LANGFUSE_TRACE_TAGS` | Comma-separated list of trace attributes to attach as Langfuse tags. Available values: `ticket_key`, `ticket_type`, `project_id`, `workflow_step`, `repo`, `pr_number`, `ci_status`, `event_source`, `event_type`, `llm_model`. Default: empty (no tags). |
| `LANGFUSE_TRACE_METADATA` | Comma-separated list of trace attributes to attach as Langfuse metadata. Available values: same as tags plus `retry_count`, `system_prompt_length`. Default: empty (no metadata). |

### Grafana Dashboards

These variables are used by `docker-compose.yml`, `devtools/docker-compose.dev.yml`, and `devtools/grafana/compose.grafana.yml`.

| Variable | Description |
|----------|-------------|
| `GRAFANA_PORT` | Host port for Grafana (default: `3010`) |
| `GRAFANA_ADMIN_USER` | Grafana admin user (default: `admin`) |
| `GRAFANA_ADMIN_PASSWORD` | Grafana admin password (default: `grafana`) |
| `LANGFUSE_DOCKER_NETWORK` | External Docker/Podman network for self-hosted Langfuse when using `devtools/grafana/compose.langfuse-network.yml` (default: `langfuse_default`) |
| `CLICKHOUSE_HOST` | Langfuse ClickHouse host reachable from the Grafana container |
| `CLICKHOUSE_PORT` | Langfuse ClickHouse native protocol port (default: `9000`) |
| `CLICKHOUSE_DATABASE` | Langfuse ClickHouse database (default: `default`) |
| `CLICKHOUSE_USER` | Langfuse ClickHouse user |
| `CLICKHOUSE_PASSWORD` | Langfuse ClickHouse password |
| `PROMETHEUS_HOST` | Prometheus host for standalone Grafana compose |
| `PROMETHEUS_PORT` | Prometheus port for standalone Grafana compose |
| `REDIS_HOST` | Redis host for standalone Grafana compose |
| `REDIS_PORT` | Redis port for standalone Grafana compose |

## Workflow Statistics and Weekly Reporting

These settings configure resource tracking, cost metrics, cost alerting, and automated weekly reporting features within the Forge orchestrator.

### Environment Variables and Pydantic Properties

| Environment Variable | Settings Property | Type | Default Value | Description |
|----------------------|-------------------|------|---------------|-------------|
| `STATS_COST_ALERT_ENABLED` | `stats_cost_alert_enabled` | `bool` | `True` | Toggle to enable/disable cost alerts if token or dollar thresholds are exceeded. |
| `STATS_COST_ALERT_THRESHOLD_TOKENS` | `stats_cost_alert_threshold_tokens` | `int` | `1,000,000` | Cumulative token limit threshold (input + output across all stages) for triggering warnings. |
| `STATS_COST_ALERT_THRESHOLD_DOLLARS` | `stats_cost_alert_threshold_dollars` | `float \| None` | `None` | Optional monetary threshold in USD for triggering cost warnings. If set, cost warnings are triggered based on calculated costs instead of token counts. |
| `LLM_PRICING` | `llm_pricing` | `dict[str, dict[str, float]]` | (JSON) | Pricing structure mapping LLM models or model substrings (longest match wins) to input and output token rates per million tokens. Configured as a JSON-encoded string when set via environment variables. |
| `FORGE_WEEKLY_REPORT_NOTIFY` | `weekly_report_notify` | `str` | `""` | Global fallback notification recipients. Set to a comma-separated list of Jira account IDs (e.g. `abc123,def456`) or the special value `project-leads` to defer to the per-project property `forge.weekly-report.notify`. |
| `JIRA_SERVICE_ACCOUNT_ID` | `jira_service_account_id` | `str` | `""` | Jira account ID of the Forge service account used to post comments. When set, only comments authored by this account are treated as Forge comments when checking whether the stats comment is the final comment on a ticket (see ensure_stats_is_final_comment). |

The default JSON structure for `LLM_PRICING` rates (USD per million tokens) is as follows:

```json
{
  "claude-opus-4": {"input": 15.00, "output": 75.00},
  "claude-sonnet-4": {"input": 3.00, "output": 15.00},
  "claude-haiku-3-5": {"input": 0.80, "output": 4.00},
  "gemini-3.5-flash": {"input": 1.50, "output": 9.00},
  "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
  "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
  "gemini-2.0-flash": {"input": 0.10, "output": 0.40}
}
```

### Jira Project Properties

You can customize the notification list for a specific project. Setting this property via the Jira project properties REST API overrides or resolves the `FORGE_WEEKLY_REPORT_NOTIFY` setting:

- **Property Name:** `forge.weekly-report.notify`
- **Value:** A JSON array of Jira account IDs to be tagged/notified on weekly reports (e.g., `["account-id-1", "account-id-2"]`).


### MCP Servers

MCP server configuration lives in `mcp-servers.json`, not `.env`. See the [MCP servers section](https://github.com/forge-sdlc/forge/blob/main/mcp-servers.json) of the repository.
