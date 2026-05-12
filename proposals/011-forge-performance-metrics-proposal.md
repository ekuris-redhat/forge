# Forge SDLC Performance Metrics Proposal
**Author:** ekuris-redhat
**Date:** May 10 2026
**Version:** 1.0 Draft
## Summary
Forge is a system that uses AI to automate software development. It helps with planning, implementation and review. This proposal is about measuring how well Forge works.
Forge uses tools like Jira, GitHub and LLM. We want to track how long it takes to finish a feature, how much it costs, and if it's worth it.
## 2. Motivation
Software teams want to deliver but also keep quality high. Manual workflows are hard to predict. Forge uses AI to automate tasks. We need to quantify the actual increase in productivity.
We want to answer questions like:
- Is the quality good?
- Are we spending money wisely?
- Where should we improve next?
## 3. Methodology
### 3.1 Iteration Tracking
An **iteration** is when AI generates something and a human reviews it. We track how many iterations it takes to finish a feature.
| Iteration Outcome | Description |
|--------------------|-------------|
| **Approved** | Accepted on this try |
| **Revised** | Human requests changes |
| **Q&A** | Human asks questions |
| **Blocked** | Workflow can't proceed |
### 3.2 Data Sources
| Source | Metrics Captured |
|--------|-----------------|
| **Prometheus** | Workflow data, time and attempts |
| **Langfuse** | AI call data, latency and cost |
| **GitHub API** | PR lifecycle data |
| **Jira API** | Ticket lifecycle data |
| **Redis Checkpoints** | Workflow state data |
### 3.3 Aggregation Architecture
The proposed pipeline has three stages:
- **Bronze (Raw Data)**
- **Silver (Cleaned Data)**
- **Gold (KPIs and Dashboards)**
## 4. Feature & Initiative Inventory Summaries
### 4.1 Feature Workflow
**Description:** This workflow transforms a Jira Feature ticket into a merged pull request.
**Stages and Iteration Metrics:**
| # | Stage | AI Action | Iteration Target | Metric |
|---|-------|-----------|-------------------|--------|
| 1 | PRD Generation | AI generates PRD | ≤ 2 iterations | `prd_iteration_count` |
| 2 | Spec | AI generates specs | ≤ 2 iterations | `spec_iteration_count` |
| 3 | Epic Decomposition | AI breaks feature into epics | ≤ 2 iterations | `epic_iteration_count` |
| 4 | Task Generation | AI generates tasks | ≤ 2 iterations | `task_iteration_count` |
| 5 | Code Implementation | Code generated | 1 iteration | `impl_success_rate` |
| 6 | Local Code Review | AI reviews diff | ≤ 2 passes | `local_review_pass_count` |
| 7 | PR Creation | Fork-based PR | 1 iteration | `pr_creation_success_rate` |
| 8 | CI Validation | Auto-fix pipeline | ≤ 5 attempts | `ci_fix_attempt_count` |
| 9 | AI Code Review | AI reviews PR | 1 iteration | `ai_review_findings_count` |
| 10 | Human Review | Developer reviews | ≤ 2 rounds | `human_review_rounds` |
**KPIs:**
- `feature_e2e_cycle_time`
- `feature_total_iterations`
- `feature_human_wait_time`
- `feature_ai_compute_time`
- `feature_token_cost`
### 4.2 Bug Workflow
**Description:** A simple workflow for bug tickets.
**Stages and Iteration Metrics:**
| # | Stage | Iteration Target | Metric |
|---|-------|-------------------|--------|
| 1 | Root Cause Analysis | ≤ 2 iterations | `rca_iteration_count` |
| 2 | Fix Implementation | 1 iteration | `bug_fix_success_rate` |
| 3 | CI Validation | ≤ 3 attempts | `bug_ci_fix_attempts` |
| 4 | Review & Merge | ≤ 2 rounds | `bug_review_rounds` |
**KPIs:**
- `bug_resolution_time`
- `bug_total_iterations`
- `bug_rca_accuracy`
### 4.3 Q&A Mode
**Description:** Humans can ask questions, about generated artifacts.
**Impact Metrics:**
| Metric | Description | Target |
|--------|-------------|--------|
| `qa_interactions_per_feature` | Q&A exchanges | Track trend |
| `qa_to_revision_ratio` | Q&A to revision ratio | > 60% |
| `qa_response_latency` | AI response time | < 30 seconds |
---
### 4.4 Retryable Blocked State
We added a feature called Retryable Blocked State.
**Description:** When a workflow hits an error that can not be recovered it enters a blocked state. Now we have a way to resume from the failure point by adding a special label.
**Impact Metrics:**
| Metric | Description | Target |
|--------|-------------|--------|
| `retry_count_per_workflow` | Number of retries triggered per workflow | We aim for one or less on average |
| `retry_recovery_rate` | Percentage of retries that successfully resume | We want more than 90 percent |
| `retry_wasted_compute_saved` | Estimated tokens/time saved vs. full restart | We will track savings |
**Iteration Impact:** This new feature eliminates wasted full-workflow restarts. Each retry saved prevents three to ten iterations.
---
### 4.5 CI Gate Skip
We implemented a feature called CI Gate Skip.
**Description:** Humans can skip CI gates via PR comment when a failure is known to be irrelevant.
**Impact Metrics:**
| Metric | Description | Target |
|--------|-------------|--------|
| `ci_gates_skipped_total` | Number of gates skipped across all PRs | We will track for abuse monitoring |
| `ci_skip_vs_fix_ratio` | Ratio of skipped gates vs. auto-fixed gates | We aim for less than 15 percent skipped |
| `ci_skip_post_merge_regression` | Defects in production tied to skipped gates | Our target is zero |
**Iteration Impact:** This feature reduces CI fix attempt ceiling from five to effective zero for known-flaky gates saving one to five iterations per affected PR.
---
### 4.6 PR Description Sync
We have a feature called PR Description Sync.
**Description:** After each CI fix commit the PR description is automatically regenerated to reflect the state of changes.
**Impact Metrics:**
| Metric | Description | Target |
|--------|-------------|--------|
| `pr_desc_sync_count` | Number of description regenerations per PR | We will track this as it correlates with CI fix count |
| `pr_desc_sync_latency` | Time to regenerate description | We aim for less than 15 seconds |
| `review_time_after_sync` | Whether synced descriptions reduce human review time | We will compare pre and post |
**Iteration Impact:** This feature indirectly improves human review quality potentially reducing review round iterations.
---
### 4.7 Dedicated Review Implementation Node
We implemented a feature called Dedicated Review Implementation Node.
**Description:** A dedicated workflow node that handles PR review feedback by reentering implementation context applying requested changes and pushing updated code.
**Impact Metrics:**
| Metric | Description | Target |
|--------|-------------|--------|
| `review_feedback_items` | Number of review comments per PR | We will track the trend |
| `review_fix_success_rate` | Percentage of review feedback items auto-resolved | We want more than 85 percent |
| `review_resubmission_count` | Number of times a PR is re-reviewed after AI fixes | We aim for one or less |
**Iteration Impact:** This feature converts what was an implement-push-rereview cycle into a single automated iteration. We expect to save one to three iterations per PR with review feedback.
---
### 4.8 Dynamic Skill Loading
We have a feature called Dynamic Skill Loading.
**Description:** Skills are resolved per-ticket based on the Jira project key with fallback to default skills.
**Impact Metrics:**
| Metric | Description | Target |
|--------|-------------|--------|
| `skill_override_usage` | Percentage of workflows using project-specific skills vs. defaults | We will track adoption |
| `iteration_count_by_skill_set` | Compare iteration counts between default and custom skills | We want custom to be less than or equal to default |
| `skill_load_latency` | Time to resolve and load skill configuration | We aim for less than 500 milliseconds |
**Iteration Impact:** Teams with well-tuned custom skills should see 15 to 25 percent fewer iterations than those using defaults.
---
### 4.9 Skill Packages
We implemented a feature called Skill Packages.
**Description:** Skills can be installed from Git URLs managed via CLI with SHA-based change detection and lock files.
**Impact Metrics:**
| Metric | Description | Target |
|--------|-------------|--------|
| `skill_packages_installed` | Number of external skill packages in use | We will track adoption |
| `skill_package_update_frequency` | How often packages are updated | We will track |
| `cross_project_iteration_variance` | Iteration count variance across projects using shared skill packages | We want lower variance |
**Iteration Impact:** Standardized skill packages should normalize iteration counts across projects reducing outliers.
---
### 4.10 Repository Configuration via Jira
We have a new feature called Repository Configuration via Jira.
**Description:** Per-project repository configuration stored in Jira project properties eliminating hardcoded repo mappings.
**Impact Metrics:**
Metric | Description | Target |
|--------|-------------|--------|
| `repo_config_resolution_time` | Time to resolve repository configuration | We aim for less than 200 milliseconds |
| `multi_repo_feature_rate` | Percentage of features spanning multiple repositories | We will track |
| `config_error_rate` | Misconfigurations causing workflow failures | We want less than one percent |
**Iteration Impact:** This feature eliminates configuration-related workflow failures, which previously caused blocked states and wasted iterations.
---
### 4.11 Observability Pipeline
We are working on an Observability Pipeline.
**Description:** A data pipeline that aggregates metrics from sources into unified SDLC KPIs.
**Implementation Status:** This is a prototype.
**Iteration Tracking for This Initiative:**
| Milestone | Estimated Iterations | Status |
|-----------|---------------------|--------|
| Bronze layer | 3 to 5 iterations | In progress |
| Silver layer | 4 to 6 iterations | Planned |
| Gold layer | 3 to 5 iterations | Planned |
---
## 5. Open Proposals
| Proposal | Description | Expected Iteration Savings |
|----------|-------------|---------------------------|
| `/forge hint` | Inject context hints for CI fix agent | One to two fewer CI fix attempts |
| Pre-PR Validation Gate | Skill-defined checks before PR creation | Catch issues earlier saving two to four iterations |
| Shared Workspace | Shared workspace across workers | Reduce context reconstruction overhead |
---
## 6. Cost-Benefit Analysis
### 6.1 Cost Components
| Cost Category | Measurement | Current Baseline |
|---------------|-------------|-----------------|
| **LLM Token Costs** | tokens and price per token | We track via Langfuse |
| **Compute Infrastructure** | container runtime and FastAPI workers | Fixed monthly |
| **CI/CD Costs** | GitHub Actions minutes consumed per PR | GitHub billing API |
| **Human Time** | Hours spent reviewing and approving AI-generated artifacts | Jira time-in-status |
### 6.2 Benefit Components
| Benefit Category | Measurement | Expected Impact |
|------------------|-------------|-----------------|
| **Developer Time Saved** | Hours saved per feature | 60 to 80 percent reduction |
| **Faster Time-to-Merge** | PR creation to merge time | 50 to 70 percent faster |
| **Reduced Defect Rate** | Post-merge bugs, per feature | 20 to 40 percent fewer |
### 6.3 Cost-Benefit Model
Net Value per Feature = (Manual Development Cost) - (Forge AI Cost + Human Review Cost)
Where:
Manual Development Cost = average development hours x hourly rate
Forge AI Cost = tokens x token price + compute cost share
Human Review Cost = (approval gates x average review minutes / 60) x hourly rate
Return on Investment (ROI) = (Manual Development Cost - Total Forge Cost) / Total Forge Cost x 100%
**Break-Even Analysis:**
Forge becomes cost-effective when the token and infrastructure cost per feature is less than the developer hours it replaces. Based on pricing and typical feature scope:
* Small features (1 epic 2-3 tasks):
Estimated Manual Effort: 16-24 developer hours
Estimated Forge Cost: around $5-15 in tokens and infrastructure
Estimated Savings: 12-20 hours
* Medium features (2-3 epics 5-8 tasks):
Estimated Manual Effort: 40-80 developer hours
Estimated Forge Cost: $15-40 in tokens and infrastructure
Estimated Savings: 30-60 hours
* Large features (4+ epics 10+ tasks):
Estimated Manual Effort: 100-200 developer hours
Estimated Forge Cost: $40-100 in tokens and infrastructure
Estimated Savings: 70-150 hours
### 6.4 Iteration Cost
Each additional iteration has a direct cost:
* AI iteration: around $0.50-$3.00 in token costs
* Human iteration: around 15-30 minutes of review time per revision round
* CI iteration: around $0.10-$0.50 in GitHub Actions compute and $0.50-$2.00 in AI analysis tokens
**Optimization target:** Reducing iterations per feature from 8-15 to 3-6 yields cost savings and cycle time improvements.
## 7. Proposed Reporting
### 7.1 Real-Time Dashboard
* **Panel 1. Workflow Funnel**
Features Started: 100
PRD Approved: 92
Spec Approved: 88
Epics Approved: 85
Tasks Approved: 82
PRs Merged: 78
* **Panel 2. Iteration Distribution**
Histogram of iterations per stage across all features
Breakdown by skill set
Trend line over time
* **Panel 3. Cost Tracker**
Token spend per feature
Running total vs. Estimated development cost
ROI percentage over rolling 30-day window
* **Panel 4. Cycle Time**
Median and P95 end-to-end cycle time
Breakdown by stage
Human wait time vs. AI compute time ratio
### 7.2 Weekly Report
Automated digest including:
* Features completed and their iteration profiles
* Top iteration outliers
* Cost summary and ROI trend
* Skill effectiveness comparison
* CI fix success rates and common failure categories
## 8. Implementation Roadmap
| Phase | Scope | Timeline | Dependencies |
| --- | --- | --- | --- |
| Phase 1 | Instrument iteration counters | 2 weeks | forge core |
| Phase 2 | Deploy forge-observability bronze layer | 3 weeks | forge-observability PR #1 |
| Phase 3 | Build silver layer | 3 weeks | Phase 2 |
| Phase 4 | Build gold layer | 2 weeks | Phase 3 |
| Phase 5 | Implement automated weekly reporting | 1 week | Phase 4 |
| Phase 6 | Post-evaluation agent | 4 weeks | Phase 4 |
## 9. Success Criteria
| Metric | Baseline (Month 1) | Target (Month 6) |
| --- | --- | --- |
| Average iterations per feature | 10-15 | 5-8 |
| CI fix success rate | 70% | 90%+ |
| PRD pass approval rate | 50% | 75%+ |
| Spec first-pass approval rate | 55% | 80%+ |
| End-to-end feature cycle time | 5-7 days | 2-3 days |
| Token cost per feature | $30-40 | $15-25 |
| ROI vs. Manual development | 2:1 | 5:1+ |
| Workflow failure/blocked rate | 15% | < 5% |
## 10. Risks and Mitigations
| Risk | Impact | Mitigation |
| --- | --- | --- |
| Iteration metrics gaming | Reduced code quality | Track post-merge defect rate |
| LLM cost spikes | Budget overruns | Per-node model tier selection |
| Observability pipeline latency | Stale dashboards | Stream processing |
| Single-contributor risk | Bus factor = 1 | Accelerate contributor onboarding |
| Skill drift | Inconsistent quality | Skill packages with version pinning |
## 11. Conclusion
The proposed solution aims to establish an analytics layer to transform raw telemetry into actionable SDLC performance metrics. The critical gap is addressed by defining iteration count per stage as the primary performance unit. The cost-benefit model shows that Forge is cost-effective with upside as skills mature and iteration counts decrease. The recommended next step is to prioritize the forge-observability pipeline.
*Prepared for the forge-sdlc organization. Based on analysis of repositories: forge-poller-plugin and forge-observability, as of May 10 2026.*

