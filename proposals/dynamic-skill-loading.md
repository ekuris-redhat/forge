# Proposal: Dynamic Skill Loading by Jira Project

**Author:** eshulman2
**Date:** 2026-04-19
**Status:** Implemented

## Summary

Forge currently loads agent skills from a single shared directory, applying the same instructions to every ticket regardless of which Jira project it belongs to. This proposal introduces two related changes:

1. **Per-skill project overrides**: teams can place individual skill overrides in a project-specific directory; for any skill not overridden, Forge falls back to the shared default.
2. **Plumbing/domain separation**: a clear authoring rule that Forge operational protocol belongs in system prompts, not in skills, so that team-authored skills only need to contain domain knowledge.

## Motivation

### Problem Statement

All Forge agent skills (PRD generation, spec generation, CI fix, implementation guidance, etc.) are loaded from a single shared directory. As Forge manages tickets across multiple Jira projects — each potentially representing a different team, codebase, or technology stack — the one-size-fits-all skill set creates friction:

- A Go project and a Python project need different implementation conventions
- An OpenShift project has CI failure categories (e2e-infra, Prow, DevStack) that are meaningless to a generic services team
- A team may want a different PRD or spec format without affecting all other projects
- The `analyze-ci` skill contains deep OpenShift-specific knowledge that actively misleads agents working on unrelated stacks

### Current Workarounds

Teams embed project-specific instructions inside ticket descriptions or comments, rely on `CLAUDE.md` in the target repository (which helps for implementation but not for orchestrator-side generation), or accept the shared defaults and manually revise generated artifacts.

## Proposal

### Part 1: Per-Skill Fallback

#### Overview

Introduce a resolver that derives the Jira project key from a ticket key (`AISOS-123` → `aisos`) and looks up individual skills from a project-specific directory at `skills/{project}/{skill-name}/`. If a skill is found there, it is used. If not, Forge falls back to the default `skills/default/{skill-name}/`. This is per-skill resolution, not an all-or-nothing directory replacement.

The same resolver is used by both the orchestrator agent and the container agent so behavior is consistent across the full workflow.

#### Directory Structure

```
skills/
├── default/                  # default skills (always present)
│   ├── generate-prd/
│   ├── generate-spec/
│   ├── analyze-ci/
│   ├── fix-ci/
│   └── ...
└── aisos/                    # project-specific overrides (optional)
    └── analyze-ci/           # only this skill is overridden for AISOS tickets
        └── SKILL.md          # all other skills fall back to default/
```

A team only needs to provide skills they actually want to customize. Skills absent from the project directory are served from `skills/default/` automatically.

#### New: `src/forge/skills/resolver.py`

```python
def resolve_skill_paths(ticket_key: str, skills_dir: Path) -> list[str]:
    """Return ordered skill source paths for Deep Agents.

    Deep Agents loads sources in order and deduplicates by skill name,
    with later sources overriding earlier ones (last wins). So defaults
    come first and the project override comes last, giving project skills
    precedence over any same-named default.
    """
    default_dir = skills_dir / "default"

    if "-" not in ticket_key:
        return [str(default_dir) + "/"]

    project = ticket_key.split("-")[0].lower()
    override_dir = skills_dir / project

    if not override_dir.is_dir():
        return [str(default_dir) + "/"]

    # default first, project override last (wins on name collision).
    return [str(default_dir) + "/", str(override_dir) + "/"]
```

Deep Agents loads skills from each source in order and deduplicates by skill name using a dict — later sources overwrite earlier ones. This is implemented in `deepagents.middleware.skills` and is deterministic: each skill name resolves to exactly one `SKILL.md` path. No alternative implementation is needed.

#### Modified: `src/forge/sandbox/runner.py`

Pass `ticket_key` into `_get_skill_mounts()` and call `resolve_skill_paths` to determine which directories to mount into the container, in order.

#### Modified: `src/forge/integrations/agents/agent.py`

Call `resolve_skill_paths` when constructing the orchestrator agent's skill context, replacing the current hardcoded path. Pass the resulting list as the agent's skill paths.

No changes to skill file formats, agent prompts, or the container entrypoint.

#### User Experience

A team maintaining the `AISOS` Jira project creates `skills/aisos/analyze-ci/SKILL.md` with their own CI failure categories for their stack. From that point, any `AISOS-*` ticket uses their custom `analyze-ci` skill. All other skills (generate-prd, generate-spec, implement-task, etc.) continue to use the defaults. No config change, no restart — just a new directory.

```
# AISOS-123, skills/aisos/ contains only analyze-ci:
resolver("AISOS-123") → [skills/default/, skills/aisos/]
  analyze-ci  → skills/aisos/analyze-ci/   ✓ override
  generate-prd → skills/default/generate-prd/  ✓ fallback

# OPENSHIFT-456 with no override directory:
resolver("OPENSHIFT-456") → [skills/default/]
  all skills  → skills/default/  ✓ fallback

# MYPROJ-789, skills/myproj/ contains all skills:
resolver("MYPROJ-789") → [skills/default/, skills/myproj/]
  all skills  → skills/myproj/  ✓ full override
```

Projects without an override directory see no behavior change.

---

### Part 2: Plumbing/Domain Separation

#### The Distinction

Forge skills contain two categories of content that serve different purposes and have different owners:

**Plumbing** — Forge operational protocol that is always locked. This includes:
- How to interact with `.forge/` directory files (`fix-plan.md`, `review-comments.md`, `handoff.md`, etc.)
- Commit rules and git hygiene requirements
- Workspace setup and task context handoff
- Label management and workflow state transitions (handled programmatically, not in skills)

**Domain** — Team-specific knowledge that teams should be able to customize. This includes:
- Output format and document structure (what a PRD, spec, or epic looks like)
- Process steps (how to analyze a CI failure, how to decompose an epic)
- Quality criteria and checklists
- Technology-specific conventions (CI tooling, testing frameworks, language idioms)
- Failure categorizations (e2e-infra, flaky, compile, etc.)

#### Authoring Rule

**Plumbing belongs in system prompts, not in skills.**

- Forge operational protocol for the container agent belongs in `container-system.md`
- Forge operational protocol for the orchestrator agent belongs in `system.md`
- Skills must contain only domain content

This rule exists so that team-authored skills are purely additive: a team writing an override skill only needs to understand their domain. They do not need to know how Forge's internal file protocol works, and they cannot accidentally override it.

#### Current State

The existing `skills/default/` skills are already largely compliant with this rule. Labels are applied programmatically. The `.forge/` directory protocol for the container agent is already established in `container-system.md`. The few remaining references to Forge-internal paths within skills (e.g. `.forge/fix-plan.md` in `analyze-ci` and `fix-ci`) are operationally necessary and acceptable because they define the interface between two collaborating skills — this is domain knowledge about the workflow, not agent lifecycle plumbing.

#### Going Forward

When adding new skills or modifying existing ones:

1. If the instruction governs how the agent operates within Forge (commits, workspace, handoff), it belongs in the relevant system prompt.
2. If the instruction governs what the agent produces or how it reasons about the problem domain, it belongs in the skill.
3. Skills that reference `.forge/` files are acceptable where the files are part of the inter-skill interface (e.g., `analyze-ci` writing a plan that `fix-ci` consumes). Skills must not reference Forge lifecycle files (e.g., `handoff.md`) — those are managed by the system prompt.

---

### Part 3: Default Skills Must Be Stack-Agnostic Baselines

#### The Problem

The per-skill fallback only works correctly if the default skills are genuinely useful to any team. A team that does not override `analyze-ci` should get a reasonable baseline, not a skill written for OpenShift CI that actively misleads agents about their environment (Prow log bundles, DevStack failures, OpenStack API timeouts, e2e-infra categories).

Currently the default `analyze-ci` skill is deeply OpenShift-specific. Used by a Go services team or a Python backend team, it would cause the agent to look for Prow artifacts that don't exist and apply failure categories that don't apply.

#### The Rule

**Default skills in `skills/default/` must contain only knowledge applicable to any software project.** Stack-specific knowledge belongs in a project override.

What belongs in defaults:
- General failure categories (compile error, lint, format, unit test, flaky)
- Language-agnostic lint and format tooling tables (the current `local-code-review` approach is a good model)
- Generic commit hygiene and code review criteria
- SDLC process structure (what a PRD contains, how to decompose epics)

What does not belong in defaults:
- CI platform specifics (Prow log bundle format, GitHub Actions artifact commands)
- Infrastructure-specific failure categories (DevStack, OpenStack, cluster bootstrapping)
- Project-specific tooling (controller-gen, operator-sdk, specific make targets)
- Domain-specific CI heuristics (the probabilistic code bug analysis, stuck-vs-slow timing analysis)

#### Required Audit

As part of this proposal's implementation, the existing `skills/default/` defaults must be audited and made stack-agnostic. The current `analyze-ci` skill is the primary offender — its OpenShift-specific content should be extracted and become the starting point for `skills/openshift/analyze-ci/SKILL.md`.

The default `analyze-ci` skill should be rewritten to cover only:
- How to fetch and read CI logs generically (curl, gh, basic log download)
- General failure categories: compile, lint, format, unit-test, flaky, infra
- The principle of distinguishing fixable-by-code from skip

Teams with complex CI environments (OpenShift, specialized cloud infrastructure) provide their own override with the depth they need.

#### Going Forward

When adding new content to a default skill, ask: "Would this instruction make sense in a Java microservices project? A Rust CLI tool? A Python data pipeline?" If the answer is no, it belongs in a project-specific override, not in the default.

---

## Alternatives Considered

| Alternative | Pros | Cons | Why Not |
|-------------|------|------|---------|
| All-or-nothing directory replacement (original proposal) | Simple resolver | Teams must write every skill from scratch even to change one | Too coarse; forces duplication of all default skills |
| Config file mapping project keys to skill directories | Explicit, auditable | Yet another config file to maintain; same effect as directory convention | Convention over configuration is simpler |
| FORGE.md + SKILL.md split within each skill | Clean separation enforced by structure | Extra complexity; almost no real plumbing lives in current skills | Overkill; plumbing/domain split is an authoring rule, not a structural enforcement problem |
| Skills from the target repository | Teams own skills in their repo | Requires cloning before knowing which skills to use; chicken-and-egg for PRD generation | Valid future direction, out of scope |

## Implementation Plan

### Phases

1. **Phase 0:** Move existing `plugins/forge-sdlc/skills/` to `skills/default/`. Update the hardcoded default path in `agent.py` and `runner.py`. No behavioral change. (~1 hour)
2. **Phase 1:** `src/forge/skills/resolver.py` + unit tests. No production impact. (~2 hours)
3. **Phase 2:** Wire resolver into `runner.py` (container agent) and `agent.py` (orchestrator agent). (~half day)
4. **Phase 3:** Integration smoke test: create a minimal override for a test project with one skill, confirm override is used and other skills fall back correctly. (~half day)
5. **Phase 4:** Audit `skills/default/` against the plumbing/domain rule. Move any plumbing content found into the appropriate system prompt. Document the authoring rule in `skills/README.md`. (~half day)
6. **Phase 5:** Audit default skills for stack-specific content. Rewrite `analyze-ci` as a stack-agnostic baseline. Extract the current OpenShift-specific version to `skills/openshift/analyze-ci/SKILL.md`. Review remaining skills for OpenShift or platform assumptions. (~half day)

### Dependencies

- [ ] Resolver must be importable from both `forge.sandbox` and `forge.integrations.agents` without circular imports — place in `forge.skills.resolver`

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Malformed ticket key (no `-` separator) crashes resolver | Low | Low | Guard with `if "-" not in ticket_key: return default` |
| Override directory accidentally applied to wrong project due to key prefix collision | Low | Low | Match on full prefix before `-`, not substring |
| Team writes plumbing into their override skill, duplicating system prompt content | Low | Low | Document the authoring rule; review team skills during onboarding |

## Open Questions

- [x] Should Forge log which skill directory was selected for each skill on each invocation? Useful for debugging but adds noise. answer: yes
- [x] Should per-project templates be supported alongside per-project skills? (e.g. `skills/aisos/templates/prd-template.md`) Some skills reference templates by path; teams may want to customize template structure without replacing the full skill process. answer: no
- [x] Future: should project teams be able to keep their skills in their own repository rather than in Forge's `skills/` directory? answer: yes but this is for a different proposal
