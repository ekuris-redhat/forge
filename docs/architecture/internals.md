# Internals

## Runtime and Deployment Topology

### Process Topology

Forge runs as two process types plus Redis:

- **Gateway process**: A single FastAPI/Uvicorn process. Stateless; can be load-balanced if needed. No special host requirements beyond network access to Redis.
- **Worker process(es)**: One or more `OrchestratorWorker` processes. Each creates its own Redis consumer group member. Workers **must run on a host with Podman installed** and permission to spawn rootless containers. Each worker can run up to 20 concurrent tasks (configurable via `QUEUE_MAX_CONCURRENT_TASKS`), bounded by an `asyncio.Semaphore`.
- **Redis**: Single-instance Redis server. No Sentinel or Cluster configuration exists; HA must be provided externally if required.

### Scaling Constraints

Gateway and Worker communicate only through Redis and can be deployed on separate hosts. However, horizontal Worker scaling has a **known limitation**: per-ticket event serialization uses an in-process `asyncio.Lock`, not a distributed lock. If two Worker processes receive events for the same ticket concurrently, they will process them in parallel with no coordination. See Known Limitations in the [Reference](reference.md#known-limitations) section for details.

### Container Lifecycle

- Containers are named `forge-{ticket_key}-{short_uuid}` and are removed after execution by default
- Setting `FORGE_CONTAINER_KEEP=true` preserves failed containers for debugging
- Workspace directories are cleaned up via `podman unshare rm -rf` (to handle root-owned files), with `shutil.rmtree` as a fallback
- Stale workspaces older than 24 hours are eligible for cleanup via `cleanup_stale_workspaces()`

### Required Connectivity

- Workers --> Redis (event consumption, checkpoint read/write, retry queue)
- Gateway --> Redis (event publishing)
- Workers --> Jira API (comments, labels, transitions)
- Workers --> GitHub API (branches, commits, PRs, reviews)
- Workers --> LLM provider (Anthropic API or Vertex AI)
- Workers --> Langfuse (optional, trace ingestion)
- Containers --> LLM provider (code generation)
- Containers --> Langfuse (optional, in-container tracing)
- Containers --> internet (for dependency installation; network mode configurable via `FORGE_SANDBOX_NETWORK`, default `slirp4netns`)

### What Is Lost if Redis Is Lost

Redis holds both ephemeral queues and durable state. If Redis data is lost:

- All in-flight events in the streams are lost (unprocessed webhooks)
- All workflow checkpoint state is lost (paused workflows cannot resume)
- The retry queue and dead-letter queue contents are lost
- PR-to-ticket index mappings are lost (webhook routing for PR events will fail until rebuilt)
- Deduplication keys are lost (duplicate event processing may occur temporarily)

Operators should configure Redis persistence (RDB snapshots, AOF, or both) appropriate to their durability requirements. Forge does not configure Redis persistence itself.

## State, Events, and Concurrency Model

### Delivery Guarantee: At-Least-Once

Forge uses **at-least-once** event processing. Redis consumer groups assign each stream entry to one consumer initially, but messages are acknowledged (`XACK`) only **after** successful processing. If a worker crashes between completing processing and sending the acknowledgement, the message remains in the Pending Entries List (PEL) and can be redelivered.

The system does **not** provide exactly-once semantics. There is no transaction or Lua script wrapping handler execution and acknowledgement atomically.

### Idempotency

A `DeduplicationService` using Redis `SETNX` with 24-hour TTL keys (`forge:dedup:{event_id}`) is implemented but **not yet wired into the webhook routes**. Currently, duplicate webhooks from Jira or GitHub will be processed as separate events.

Within workflows, certain operations have natural idempotency properties:

- Branch creation: `git push` to an existing branch with the same content is a no-op
- PR creation: the workflow checks for existing PRs before creating new ones
- Label operations: setting a label that already exists is idempotent in both Jira and GitHub

However, Jira comment posting and some GitHub operations are **not** idempotent. A duplicated event could result in duplicate comments.

### Pending Entry Reclaim

There is **no automated PEL reclaim mechanism**. The codebase does not use `XPENDING`, `XCLAIM`, or `XAUTOCLAIM`. If a worker crashes mid-processing before enqueuing the message for retry, the message remains in the PEL indefinitely. Recovery requires manual intervention or restarting the consumer group. This is a known limitation (see [Reference](reference.md#known-limitations)).

### Per-Ticket Ordering

Within a single worker process, events for the same ticket are serialized by an `asyncio.Lock` per ticket key. This ensures that concurrent events for ticket `AISOS-123` within one process are handled sequentially.

Across multiple worker processes, **no distributed coordination exists**. Redis consumer groups distribute messages round-robin across consumers. If events for the same ticket are assigned to different workers, they will execute concurrently. This can lead to checkpoint conflicts or race conditions on Jira/GitHub side effects.

**Current safe configuration:** Run a single Worker process per deployment, or accept that concurrent same-ticket processing may occur across workers. The in-process lock handles the common case (multiple events arriving in quick succession to the same consumer).

### Checkpoint Model

LangGraph workflow state is persisted via `AsyncRedisSaver` in Redis. The checkpoint lifecycle:

- **Thread ID** = Jira ticket key (e.g., `AISOS-123`). One ticket maps to exactly one workflow instance and one checkpoint thread.
- **Writes** happen automatically after each LangGraph node completes.
- **Reads** happen when a new event arrives for an existing ticket: the workflow resumes from the last checkpoint.
- **Deletion**: `clear_checkpoint(thread_id)` removes all checkpoint data for a ticket.
- **Redis key pattern**: `checkpoint:{thread_id}:{...}`

### Consistency Between Checkpoints and Side Effects

Checkpoint writes and external side effects (Jira comments, GitHub PRs) are **not transactional**. A node may successfully post a comment to Jira but crash before its checkpoint is written, causing the comment to be posted again on retry. Similarly, a checkpoint may be written after the node function returns but before all side effects complete.

The ordering between the Jira and GitHub event streams is **independent**. Events are consumed from both streams concurrently, and there is no ordering guarantee across streams.

## Failure and Recovery Model

### Component Failure Modes

**Gateway failure**: Incoming webhooks are dropped. Jira and GitHub will retry webhook delivery according to their own retry policies (Jira retries up to 10 times with backoff; GitHub retries based on recent failure rate). No data is lost in Redis.

**Worker failure (crash)**: In-flight messages remain in the Redis PEL. The workflow checkpoint reflects the last completed node. On restart, the worker begins consuming new messages. PEL messages require manual intervention (see Known Limitations in the [Reference](reference.md#known-limitations) section). Retry-eligible messages that were already enqueued in the retry sorted set will be picked up by any running worker.

**Redis failure**: Complete system outage. Gateway cannot enqueue events; workers cannot consume, checkpoint, or retry. All in-memory state (streams, checkpoints, retry queue, DLQ, indexes) is at risk unless Redis persistence is configured. See [What Is Lost if Redis Is Lost](#what-is-lost-if-redis-is-lost).

**LLM provider failure**: Orchestrator nodes and container agents fail. The retry mechanism handles transient LLM errors. Persistent failures exhaust retries and move the event to the dead-letter queue. The `forge:blocked` label is applied to the Jira ticket for visibility.

**Jira/GitHub API failure**: Webhook-triggered nodes fail. Rate limiting (token bucket) prevents overloading. API errors during workflow execution are handled by the retry mechanism.

**Container failure**: Non-zero exit codes are captured by the orchestrator. If `FORGE_CONTAINER_KEEP=true`, failed containers are preserved for debugging. The workflow node reports the failure, and the retry mechanism determines whether to re-attempt.

### Retry Budget and Backoff

- **Max retry attempts:** 3
- **Backoff:** Exponential: 30s initial delay, 2x multiplier, capped at 3600s (1 hour)
- **Retry queue:** Redis sorted set (`forge:retry:queue`) with score = next retry timestamp, polled every 10 seconds
- **Dead-letter queue:** Redis list (`forge:retry:dlq`). Messages that exhaust all retries are moved here. Manual requeue via `requeue_dead_letter()` resets the attempt counter.

### Crash Recovery

- **Automatic:** Workers restart and consume new messages. Retry-queue entries are picked up by any running worker. LangGraph workflows resume from the last checkpoint when a new event arrives.
- **Manual:** PEL entries from crashed workers require manual `XCLAIM` or consumer group reset. DLQ entries require manual requeue or investigation.

### Blocked Workflows and `forge:retry`

When a workflow enters an error state, the `forge:blocked` label is applied to the Jira ticket. Adding the `forge:retry` label triggers re-entry at the failed step using the last checkpoint. This works at any workflow stage, including approval gates (where it regenerates the artifact).

### Partial Multi-Repository Execution

For tickets that span multiple repositories, the task router groups tasks by repo and processes them either sequentially or in parallel (up to 5 concurrent repos via LangGraph's `Send` API). If execution fails for one repo, that repo's error is recorded but other repos continue. The `aggregate_parallel_results()` node merges results and errors from all branches.

### Approval Gate Timeout

**There is no timeout on human approval gates.** When a workflow reaches a pause gate (`>> gate`), it persists `is_paused=True` in the checkpoint and waits indefinitely for a resume event (Jira comment or label change). If approval never arrives, the workflow remains paused in Redis checkpoint state. There is no automatic escalation or expiration.

## Security and Trust Boundaries

### Webhook Authentication

Both Jira and GitHub webhook endpoints validate HMAC-SHA256 signatures using `hmac.compare_digest()` (constant-time comparison). However, signature validation is **conditional**: it only runs when the corresponding secret is configured (`JIRA_WEBHOOK_SECRET`, `GITHUB_WEBHOOK_SECRET`). If secrets are not set, the endpoint accepts unsigned payloads without warning.

**Recommendation for production:** Always configure webhook secrets. Without them, any network actor that can reach the gateway can inject events.

### Credentials in the Worker

Worker processes require:

- Redis connection credentials (`REDIS_URL`)
- Jira API token (`JIRA_API_TOKEN`): used for reading/writing tickets, comments, labels, transitions
- GitHub App credentials (`GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY`) or personal access token: used for repository operations, PR management, and webhook validation
- LLM provider credentials: either `ANTHROPIC_API_KEY` (direct API) or Google service account credentials for Vertex AI
- Langfuse credentials (optional): `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`

### Credentials in the Container

Implementation containers receive a **subset** of credentials as environment variables:

- LLM credentials (API key or Vertex AI service account, depending on backend)
- Git user identity (`GIT_USER_NAME`, `GIT_USER_EMAIL`)
- Langfuse credentials (when enabled)

Containers do **not** receive Jira credentials, GitHub tokens, or Redis credentials. All Jira/GitHub operations are performed by the orchestrator after the container exits.

### Container Isolation

- **Rootless Podman**: Containers run without root privileges on the host
- **Network**: Configurable via `FORGE_SANDBOX_NETWORK` (default: `slirp4netns`, providing NAT-based isolation)
- **Resource limits**: Memory: 4GB (configurable), CPU: 2 cores (configurable), Timeout: 30 minutes (configurable)
- **Filesystem**: Workspace mounted read-write at `/workspace` (necessary for code changes); task file mounted read-only at `/task.json`

**Not currently enforced:**

- `--security-opt no-new-privileges` is not set
- `--cap-drop ALL` is not applied (relies on Podman rootless defaults)
- No explicit seccomp profile
- Root filesystem is not read-only (`--read-only` not set)
- No AppArmor or SELinux enforcement beyond the `:Z` mount relabeling flag

### Prompt Injection Boundaries

Forge processes externally-supplied text from Jira tickets, GitHub PR descriptions, code review comments, and repository content. This text is passed to LLM prompts. The system relies on:

- **Structured prompt templates**: System prompts are loaded from versioned templates in `src/forge/prompts/v1/`, not dynamically constructed from user input
- **Repository guardrails**: The workspace manager searches cloned repos for `CONSTITUTION.md`, `AGENTS.md`, and `CLAUDE.md` files and injects them as system context, giving repo owners control over agent behavior
- **Human gates**: All generated artifacts (PRDs, specs, plans, code) must pass human approval before merging, providing a boundary against manipulated output
- **Container isolation**: Code execution happens in ephemeral containers with limited credentials, bounding the blast radius of a compromised agent

### MCP Tool Permissions

Container agents use Deep Agents with MCP tool access. The agent can read and write files within `/workspace`, run shell commands, and use MCP-configured tools. It cannot access host filesystems outside the mount, Jira/GitHub APIs directly, or Redis.

### Secret Redaction and Auditability

- LLM interactions are traced via Langfuse (when enabled), providing an audit trail of all AI-generated content
- Container stdout/stderr is captured in worker logs
- Jira comments and GitHub PR descriptions provide a human-readable record of all workflow artifacts
- Credential values are passed as environment variables, not written to files or logs
