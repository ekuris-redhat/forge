## Bug Ticket

**Summary:** {summary}

**Description:**
{description}

**Comments:**
{comments}

---

Evaluate this ticket against the following 7 required triage fields to determine if there is enough information to begin investigating:

1. steps_to_reproduce: How to trigger the bug. Satisfied if the mechanism or conditions are described even vaguely, or if the reporter says they cannot reproduce it or it is intermittent.
2. expected_vs_actual: What happened vs. what should have happened. Satisfied if either side is described.
3. environment: Runtime, OS, or infrastructure context. Almost always satisfied (e.g., if obvious, internal, or unknown). Never block on this alone.
4. affected_versions: Which version exhibits the bug. Almost always satisfied. Never block on this alone.
5. error_output: Logs, stack traces, or error messages. Satisfied if no error output exists, or is not mentioned, or if reporter has no access.
6. affected_component: Name of any service, layer, or user-facing feature. Never require file-level specificity.
7. disambiguating_context: Only flag if so generic that completely different bugs could plausibly match it.

Evaluation Philosophy:
- Default to passing ("sufficient"). Only block when a field is completely absent AND that absence genuinely prevents starting an investigation.
- If the ticket is sufficient to start investigation, output ONLY the bare string `sufficient`.
- If any required fields are completely missing and block investigation, output ONLY a bare JSON array of the missing field names (e.g., `["steps_to_reproduce", "error_output"]`).

Do not include any markdown formatting, code fences (no ```), or explanation in your response. Output only the bare string or bare JSON array.
