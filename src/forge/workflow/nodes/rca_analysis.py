"""RCA analysis nodes: analyze_bug and reflect_rca."""

import json
import logging
import tempfile
import time
from pathlib import Path

from forge.config import get_settings
from forge.integrations.jira.client import JiraClient, MissingProjectConfig
from forge.models.workflow import ForgeLabel
from forge.prompts import load_prompt
from forge.sandbox import ContainerRunner
from forge.workflow.bug.state import BugState
from forge.workflow.stats import STAGE_RCA
from forge.workflow.stats_utils import record_stage_end, record_stage_start, record_tokens
from forge.workflow.utils import update_state_timestamp
from forge.workflow.utils.jira_status import post_status_comment

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    """Estimate token count from text length (approx. 4 chars per token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


_RCA_REQUIRED_KEYS = {
    "summary",
    "code_location",
    "mechanism",
    "trigger_to_symptom",
    "hypothesis_log",
    "introduced_in",
    "confidence",
    "options",
    "reproducibility",
}
_OPTION_REQUIRED_KEYS = {"title", "description", "tradeoffs"}

MAX_ANALYSIS_RETRIES = 3
MAX_REFLECTION_ITERATIONS = 3


async def analyze_bug(state: BugState) -> BugState:
    """Run hypothesis-driven codebase analysis and write rca.json.

    Spawns a container that clones the relevant repo(s) and writes
    .forge/rca.json. Parses the artifact into rca_options and rca_content.
    Passes reflection_critique if a previous reflect_rca pass returned a critique.

    Returns:
        Updated state with rca_options and rca_content populated,
        current_node="reflect_rca". On repeated failure: current_node="escalate_blocked".
    """
    ticket_key = state["ticket_key"]
    retry_count = state.get("retry_count", 0)
    reflection_critique = state.get("reflection_critique") or ""

    settings = get_settings()
    state = {**state, **record_stage_start(state, STAGE_RCA, model_name=settings.llm_model)}
    node_start = time.monotonic()

    jira = JiraClient()

    try:
        await post_status_comment(
            jira,
            ticket_key,
            "🔍 Forge is analyzing the bug root cause — this may take a few minutes.",
        )

        issue = await jira.get_issue(ticket_key)

        try:
            repos = await jira.get_project_repos(issue.project_key)
        except MissingProjectConfig as e:
            await jira.add_comment(
                ticket_key,
                f"Cannot start RCA: repository configuration is missing for project "
                f"`{issue.project_key}`.\n\n"
                f"Set `forge.repos` on the Jira project to a comma-separated list of "
                f"`owner/repo` values, then add `forge:retry` to resume.\n\n"
                f"Details: {e}",
            )
            await jira.set_workflow_label(ticket_key, ForgeLabel.BLOCKED)
            machine_time = time.monotonic() - node_start
            state = {**state, **record_stage_end(state, STAGE_RCA, machine_time)}
            return {
                **state,
                "last_error": str(e),
                "current_node": "analyze_bug",
            }

        task_description = load_prompt(
            "analyze-bug",
            ticket_key=ticket_key,
            bug_summary=issue.summary or "",
            bug_description=issue.description or "",
            known_repos="\n".join(repos),
            reflection_critique=reflection_critique,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            runner = ContainerRunner(settings)
            result = await runner.run(
                workspace_path=workspace_path,
                task_summary=f"RCA analysis for {ticket_key}",
                task_description=task_description,
                ticket_key=ticket_key,
                task_key=f"{ticket_key}-analysis",
            )

            # Record tokens (using actual container metrics if available, else falling back to heuristic)
            if (
                result
                and isinstance(getattr(result, "input_tokens", None), int)
                and result.input_tokens > 0
            ):
                input_tokens = result.input_tokens
            else:
                input_tokens = _estimate_tokens(task_description)

            if (
                result
                and isinstance(getattr(result, "output_tokens", None), int)
                and result.output_tokens > 0
            ):
                output_tokens = result.output_tokens
            else:
                output_tokens = _estimate_tokens(result.stdout) if (result and result.stdout) else 0
            state = {**state, **record_tokens(state, STAGE_RCA, input_tokens, output_tokens)}

            if not result.success:
                raise RuntimeError(
                    f"Container failed with exit_code={result.exit_code}: {result.stderr}"
                )

            data = _harvest_rca_json(workspace_path)

        machine_time = time.monotonic() - node_start
        state = {**state, **record_stage_end(state, STAGE_RCA, machine_time)}

        return update_state_timestamp(
            {
                **state,
                "rca_options": data["options"],
                "rca_content": _format_rca_content(data),
                "reproducibility_assessment": _format_reproducibility(data),
                "current_node": "reflect_rca",
                "last_error": None,
            }
        )

    except Exception as e:
        logger.error(f"analyze_bug failed for {ticket_key}: {e}")
        new_retry = retry_count + 1
        next_node = "escalate_blocked" if new_retry >= MAX_ANALYSIS_RETRIES else "analyze_bug"
        machine_time = time.monotonic() - node_start
        state = {**state, **record_stage_end(state, STAGE_RCA, machine_time)}
        return {
            **state,
            "last_error": str(e),
            "current_node": next_node,
            "retry_count": new_retry,
        }

    finally:
        await jira.close()


def _harvest_rca_json(workspace_path: Path) -> dict:
    """Read and parse .forge/rca.json from the container workspace.

    Raises:
        FileNotFoundError: if rca.json was not written.
        ValueError: if required top-level or option keys are absent.
    """
    rca_file = workspace_path / ".forge" / "rca.json"
    if not rca_file.exists():
        raise FileNotFoundError(f"rca.json not found at {rca_file}")

    data = json.loads(rca_file.read_text())

    missing_keys = _RCA_REQUIRED_KEYS - set(data.keys())
    if missing_keys:
        raise ValueError(f"rca.json missing required keys: {missing_keys}")

    options = data.get("options", [])
    if not isinstance(options, list) or not (1 <= len(options) <= 4):
        raise ValueError(
            f"rca.json options must be a list of 1–4 items, got "
            f"{len(options) if isinstance(options, list) else type(options)}"
        )

    for i, opt in enumerate(options):
        missing_opt_keys = _OPTION_REQUIRED_KEYS - set(opt.keys())
        if missing_opt_keys:
            raise ValueError(f"option[{i}] missing required keys: {missing_opt_keys}")

    return data


def _format_rca_content(data: dict) -> str:
    """Build the human-readable rca_content string from the parsed rca.json."""
    loc = data.get("code_location", {})
    location_str = (
        f"{loc.get('file', '?')}:{loc.get('function', '?')} (lines {loc.get('line_range', '?')})"
    )

    introduced = data.get("introduced_in", {})
    intro_str = f"commit {introduced.get('commit', '?')} ({introduced.get('date', 'unknown date')})"
    if introduced.get("pr"):
        intro_str += f", PR {introduced['pr']}"

    confidence = data.get("confidence", {})
    conf_str = (
        f"{confidence.get('level', '?')} ({confidence.get('percentage', '?')}%) "
        f"— {confidence.get('rationale', '')}"
    )

    return (
        f"## Summary\n{data.get('summary', '')}\n\n"
        f"## Code Location\n{location_str}\n\n"
        f"## Mechanism\n{data.get('mechanism', '')}\n\n"
        f"## Trigger to Symptom\n{data.get('trigger_to_symptom', '')}\n\n"
        f"## Introduced In\n{intro_str}\n\n"
        f"## Confidence\n{conf_str}"
    )


def _format_reproducibility(data: dict) -> str:
    """Build the reproducibility_assessment string."""
    repro = data.get("reproducibility", {})
    feasible = repro.get("feasible", False)
    lines = [f"Reproducible: {'Yes' if feasible else 'No'}"]
    if repro.get("conditions"):
        lines.append(f"Conditions: {repro['conditions']}")
    if repro.get("test_source"):
        lines.append(f"\n```python\n{repro['test_source']}\n```")
    return "\n".join(lines)


async def reflect_rca(state: BugState) -> BugState:
    """Validate the RCA from analyze_bug for completeness and evidence quality.

    Runs a container using reflect-rca.md. Container returns either "VALID"
    or a structured critique string.

    On VALID: routes to rca_option_gate.
    On critique with reflection_count < 3: stores critique, routes back to analyze_bug.
    On critique with reflection_count >= 3: posts warning comment, routes to rca_option_gate.

    Returns:
        Updated state with current_node set appropriately.
    """
    ticket_key = state["ticket_key"]
    rca_content = state.get("rca_content") or ""
    rca_options = state.get("rca_options") or []
    reflection_count = state.get("reflection_count", 0)
    reflect_rca_retry_count = state.get("reflect_rca_retry_count", 0)

    settings = get_settings()
    state = {**state, **record_stage_start(state, STAGE_RCA, model_name=settings.llm_model)}
    node_start = time.monotonic()

    jira = JiraClient()

    try:
        task_description = load_prompt(
            "reflect-rca",
            rca_content=rca_content,
            rca_options_json=json.dumps(rca_options, indent=2),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            runner = ContainerRunner(settings)
            result = await runner.run(
                workspace_path=workspace_path,
                task_summary=f"RCA reflection for {ticket_key}",
                task_description=task_description,
                ticket_key=ticket_key,
                task_key=f"{ticket_key}-reflect",
            )

            # Record tokens (using actual container metrics if available, else falling back to heuristic)
            if (
                result
                and isinstance(getattr(result, "input_tokens", None), int)
                and result.input_tokens > 0
            ):
                input_tokens = result.input_tokens
            else:
                input_tokens = _estimate_tokens(task_description)

            if (
                result
                and isinstance(getattr(result, "output_tokens", None), int)
                and result.output_tokens > 0
            ):
                output_tokens = result.output_tokens
            else:
                output_tokens = _estimate_tokens(result.stdout) if (result and result.stdout) else 0
            state = {**state, **record_tokens(state, STAGE_RCA, input_tokens, output_tokens)}

            if not result.success:
                raise RuntimeError(
                    f"Reflection container failed with exit_code={result.exit_code}: {result.stderr}"
                )

            verdict = result.stdout.strip()

        if verdict.upper().strip() == "VALID":
            machine_time = time.monotonic() - node_start
            state = {**state, **record_stage_end(state, STAGE_RCA, machine_time)}
            return update_state_timestamp(
                {
                    **state,
                    "reflection_critique": None,
                    "current_node": "rca_option_gate",
                }
            )

        new_reflection_count = reflection_count + 1

        if new_reflection_count >= MAX_REFLECTION_ITERATIONS:
            await jira.add_comment(
                ticket_key,
                f"Reflection cap reached — proceeding with best available RCA after "
                f"{new_reflection_count} validation attempts.",
            )
            machine_time = time.monotonic() - node_start
            state = {**state, **record_stage_end(state, STAGE_RCA, machine_time)}
            return update_state_timestamp(
                {
                    **state,
                    "reflection_critique": verdict,
                    "reflection_count": new_reflection_count,
                    "current_node": "rca_option_gate",
                }
            )

        machine_time = time.monotonic() - node_start
        state = {**state, **record_stage_end(state, STAGE_RCA, machine_time)}
        return update_state_timestamp(
            {
                **state,
                "reflection_critique": verdict,
                "reflection_count": new_reflection_count,
                "current_node": "analyze_bug",
            }
        )

    except Exception as e:
        logger.error(f"reflect_rca failed for {ticket_key}: {e}")
        new_reflect_retry = reflect_rca_retry_count + 1
        next_node = (
            "escalate_blocked" if new_reflect_retry >= MAX_ANALYSIS_RETRIES else "reflect_rca"
        )
        machine_time = time.monotonic() - node_start
        state = {**state, **record_stage_end(state, STAGE_RCA, machine_time)}
        return {
            **state,
            "last_error": str(e),
            "current_node": next_node,
            "reflect_rca_retry_count": new_reflect_retry,
        }

    finally:
        await jira.close()
