# Forge Skills

Agent skills for the Forge SDLC orchestrator.

## Directory Layout

```
skills/
├── default/          # Stack-agnostic defaults used by all projects
│   ├── analyze-ci/
│   ├── generate-prd/
│   └── ...
├── openshift/        # OpenShift team overrides (example)
│   └── analyze-ci/
└── {project}/        # Per-project overrides (Jira project key, lowercase)
    └── {skill-name}/
        └── SKILL.md
```

## How Overrides Work

Skills are resolved per-ticket by Jira project key:
- `AISOS-123` → looks for `skills/aisos/` first, falls back to `skills/default/`
- A team only needs to provide the skills they want to customize
- All other skills are served automatically from `skills/default/`

## Writing a Skill Override

Create `skills/{project-key-lowercase}/{skill-name}/SKILL.md`.

The skill name must match the directory name and an existing skill name in `skills/default/`.

### What belongs in a skill (Domain content)

- Output format and document structure
- Process steps and analysis frameworks
- Quality checklists and acceptance criteria
- Technology-specific conventions (CI tooling, test frameworks, language idioms)
- Failure categorizations relevant to your stack
- References to `.forge/` inter-skill interface files (e.g., `.forge/fix-plan.md` written by `analyze-ci` and consumed by `fix-ci`)

### What does NOT belong in a skill (Plumbing)

The following belong in Forge system prompts, not skills. Do not duplicate them:

- Git commit rules or git hygiene
- `.forge/handoff.md` update instructions
- Workspace setup or task context loading
- Label management or workflow state transitions (handled programmatically)

### Skill file format

```markdown
---
name: {skill-name}
description: What this skill does and when to use it.
---

# Skill Title

...skill content...
```

The `name` field must match the directory name exactly.

## Default Skill Quality Bar

Skills in `skills/default/` must be useful to any software project regardless of stack.
Before adding stack-specific content to a default skill, ask:
"Would this make sense for a Java microservices project? A Rust CLI? A Python pipeline?"

If the answer is no, put it in a project-specific override instead.
