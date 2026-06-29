"""Specification approval gate for human-in-the-loop review.

The spec approval workflow uses labels:
- forge:spec-pending  - Spec awaiting approval
- forge:spec-approved - Spec approved (triggers epic decomposition)

To approve: Change label from forge:spec-pending to forge:spec-approved
To request revision: Add a comment with feedback (keep forge:spec-pending)
"""

import logging

from langgraph.graph import END

from forge.api.routes.metrics import record_approval, record_revision_requested
from forge.workflow.feature.state import FeatureState as WorkflowState
from forge.workflow.utils import set_paused

logger = logging.getLogger(__name__)


def spec_approval_gate(state: WorkflowState) -> WorkflowState:
    """Pause workflow for PM to review and approve the specification.

    This gate pauses the workflow until a human approves or rejects
    the generated specification. The workflow resumes when:
    - Label changes to forge:spec-approved -> continue to epic decomposition
    - Comment added with feedback -> regenerate spec with feedback

    Args:
        state: Current workflow state.

    Returns:
        State with is_paused=True.
    """
    ticket_key = state["ticket_key"]
    logger.info(f"Spec approval gate: pausing workflow for {ticket_key}")

    return set_paused(state, "spec_approval_gate")


def route_spec_approval(state: WorkflowState) -> str:
    """Route based on spec approval status.

    Args:
        state: Current workflow state.

    Returns:
        Next node name or END.
    """
    # Check if this is a question (Q&A mode) - check FIRST
    if state.get("is_question") and state.get("feedback_comment"):
        logger.info(f"Q&A mode: routing to answer_question for {state['ticket_key']}")
        return "answer_question"

    # YOLO mode: auto-approve without human input
    if state.get("yolo_mode"):
        logger.info(f"YOLO mode: auto-approving spec for {state['ticket_key']}")
        record_approval("spec")
        return "decompose_epics"

    # Check if revision was requested
    if state.get("revision_requested") and state.get("feedback_comment"):
        logger.info(f"Spec revision requested for {state['ticket_key']}")
        record_revision_requested("spec")
        return "regenerate_spec"

    # Check if still paused - END and wait for approval webhook
    if state.get("is_paused"):
        logger.info(
            f"Spec approval gate: workflow paused for {state['ticket_key']}, "
            "waiting for approval webhook"
        )
        return END

    # Spec approved, proceed to epic decomposition
    logger.info(f"Spec approved for {state['ticket_key']}, proceeding to epic decomposition")
    record_approval("spec")
    return "decompose_epics"


async def handle_out_of_order_rejection(
    ticket_key: str,
    current_node: str,
    attempted_label: str,
) -> None:
    """Handle out-of-order status transition by posting a warning and resetting the label."""
    from forge.integrations.jira.client import JiraClient
    from forge.models.workflow import ForgeLabel

    logger.warning(
        f"Out-of-order transition rejected for {ticket_key} at {current_node}: "
        f"attempted {attempted_label}"
    )

    # Determine attempted stage name for the comment
    attempted_stage = "stage"
    attempted_label_lower = attempted_label.lower()
    if "prd" in attempted_label_lower:
        attempted_stage = "spec" if "spec" in attempted_label_lower else "PRD"
    elif "spec" in attempted_label_lower:
        attempted_stage = "spec"
    elif "plan" in attempted_label_lower:
        attempted_stage = "plan"
    elif "task" in attempted_label_lower:
        attempted_stage = "tasks"

    # Specific message for spec approval out-of-order:
    # "cannot approve spec before it has been set to pending"
    if attempted_stage == "spec":
        comment = "⚠️ Out-of-order transition rejected: cannot approve spec before it has been set to pending."
    else:
        comment = f"⚠️ Out-of-order transition rejected: cannot approve {attempted_stage} before it has been set to pending."

    # Determine correct label to restore
    node_to_label = {
        "prd_approval_gate": ForgeLabel.PRD_PENDING,
        "generate_prd": ForgeLabel.PRD_DRAFTING,
        "regenerate_prd": ForgeLabel.PRD_PENDING,
        "spec_approval_gate": ForgeLabel.SPEC_PENDING,
        "generate_spec": ForgeLabel.SPEC_DRAFTING,
        "regenerate_spec": ForgeLabel.SPEC_PENDING,
        "plan_approval_gate": ForgeLabel.PLAN_PENDING,
        "decompose_epics": ForgeLabel.PLAN_DRAFTING,
        "regenerate_all_epics": ForgeLabel.PLAN_PENDING,
        "update_single_epic": ForgeLabel.PLAN_PENDING,
        "task_approval_gate": ForgeLabel.TASK_PENDING,
        "generate_tasks": ForgeLabel.TASK_GENERATED,
    }
    correct_label = node_to_label.get(current_node, ForgeLabel.PRD_PENDING)

    jira = JiraClient()
    try:
        await jira.add_comment(ticket_key, comment)
        await jira.set_workflow_label(ticket_key, correct_label)
    finally:
        await jira.close()
