"""Unit tests for stats recording in PRD and Spec generation nodes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.models.workflow import TicketType
from forge.workflow.feature.state import create_initial_feature_state
from forge.workflow.stats import STAGE_PRD, STAGE_SPEC

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_mock_jira(
    description: str = "Raw requirements text",
    summary: str = "Test Feature",
    project_key: str = "TEST",
) -> MagicMock:
    """Return a JiraClient mock with default async methods."""
    mock = MagicMock()
    mock.close = AsyncMock()
    mock.update_description = AsyncMock()
    mock.add_structured_comment = AsyncMock()
    mock.set_workflow_label = AsyncMock()
    mock.get_prd_proposals_repo = AsyncMock(return_value=None)
    mock.add_comment = AsyncMock()
    mock.get_issue = AsyncMock(
        return_value=MagicMock(
            summary=summary,
            description=description,
            project_key=project_key,
        )
    )
    return mock


def create_mock_agent(
    prd_content: str = "# Generated PRD\n\nContent here.",
    spec_content: str = "# Generated Spec\n\nAcceptance criteria here.",
) -> MagicMock:
    """Return a ForgeAgent mock with default async methods."""
    mock = MagicMock()
    mock.close = AsyncMock()
    mock.generate_prd = AsyncMock(return_value=prd_content)
    mock.generate_spec = AsyncMock(return_value=spec_content)
    mock.regenerate_with_feedback = AsyncMock(return_value="# Revised content")
    return mock


def _get_stage(result: dict, stage_name: str) -> dict:
    """Extract a stage entry from result state, or {} if absent."""
    return (result.get("stage_timestamps") or {}).get(stage_name, {})


# ---------------------------------------------------------------------------
# PRD generation stats tests
# ---------------------------------------------------------------------------


class TestGeneratePrdStatsRecording:
    """Tests for stats recording in generate_prd node."""

    @pytest.mark.asyncio
    async def test_records_stage_start_on_entry(self):
        """generate_prd should initialise the PRD stage with a started_at timestamp."""
        from forge.workflow.nodes.prd_generation import generate_prd

        mock_jira = create_mock_jira()
        mock_agent = create_mock_agent()
        state = create_initial_feature_state(
            ticket_key="TEST-1",
            ticket_type=TicketType.FEATURE,
        )

        with (
            patch("forge.workflow.nodes.prd_generation.JiraClient", return_value=mock_jira),
            patch("forge.workflow.nodes.prd_generation.ForgeAgent", return_value=mock_agent),
            patch(
                "forge.workflow.nodes.prd_generation.post_status_comment",
                new_callable=AsyncMock,
            ),
        ):
            result = await generate_prd(state)

        stage = _get_stage(result, STAGE_PRD)
        assert stage, "stage_timestamps[STAGE_PRD] should be populated"
        assert stage.get("started_at") is not None, "started_at must be set"

    @pytest.mark.asyncio
    async def test_records_stage_end_with_machine_time(self):
        """generate_prd should populate ended_at and positive machine_time_seconds."""
        from forge.workflow.nodes.prd_generation import generate_prd

        mock_jira = create_mock_jira()
        mock_agent = create_mock_agent()
        state = create_initial_feature_state(
            ticket_key="TEST-1",
            ticket_type=TicketType.FEATURE,
        )

        with (
            patch("forge.workflow.nodes.prd_generation.JiraClient", return_value=mock_jira),
            patch("forge.workflow.nodes.prd_generation.ForgeAgent", return_value=mock_agent),
            patch(
                "forge.workflow.nodes.prd_generation.post_status_comment",
                new_callable=AsyncMock,
            ),
        ):
            result = await generate_prd(state)

        stage = _get_stage(result, STAGE_PRD)
        assert stage.get("ended_at") is not None, "ended_at must be set on success"
        assert stage.get("machine_time_seconds", 0.0) >= 0.0, "machine_time must be non-negative"

    @pytest.mark.asyncio
    async def test_records_tokens_from_llm_response(self):
        """generate_prd should record non-zero token counts after LLM call."""
        from forge.workflow.nodes.prd_generation import generate_prd

        mock_jira = create_mock_jira(description="A" * 400)  # 100 estimated tokens
        mock_agent = create_mock_agent(prd_content="B" * 800)  # 200 estimated tokens
        state = create_initial_feature_state(
            ticket_key="TEST-1",
            ticket_type=TicketType.FEATURE,
        )

        with (
            patch("forge.workflow.nodes.prd_generation.JiraClient", return_value=mock_jira),
            patch("forge.workflow.nodes.prd_generation.ForgeAgent", return_value=mock_agent),
            patch(
                "forge.workflow.nodes.prd_generation.post_status_comment",
                new_callable=AsyncMock,
            ),
        ):
            result = await generate_prd(state)

        stage = _get_stage(result, STAGE_PRD)
        assert stage.get("input_tokens", 0) > 0, "input_tokens should be positive"
        assert stage.get("output_tokens", 0) > 0, "output_tokens should be positive"

    @pytest.mark.asyncio
    async def test_stats_recorded_on_missing_requirements(self):
        """generate_prd should record stage_end even when requirements are empty."""
        from forge.workflow.nodes.prd_generation import generate_prd

        mock_jira = create_mock_jira(description="")
        mock_agent = create_mock_agent()
        state = create_initial_feature_state(
            ticket_key="TEST-1",
            ticket_type=TicketType.FEATURE,
        )

        with (
            patch("forge.workflow.nodes.prd_generation.JiraClient", return_value=mock_jira),
            patch("forge.workflow.nodes.prd_generation.ForgeAgent", return_value=mock_agent),
            patch(
                "forge.workflow.nodes.prd_generation.post_status_comment",
                new_callable=AsyncMock,
            ),
        ):
            result = await generate_prd(state)

        stage = _get_stage(result, STAGE_PRD)
        assert stage.get("started_at") is not None
        assert stage.get("ended_at") is not None

    @pytest.mark.asyncio
    async def test_stats_recorded_on_exception(self):
        """generate_prd should record stage_end even when an exception is raised."""
        from forge.workflow.nodes.prd_generation import generate_prd

        mock_jira = create_mock_jira()
        mock_agent = create_mock_agent()
        mock_agent.generate_prd = AsyncMock(side_effect=RuntimeError("LLM failure"))
        state = create_initial_feature_state(
            ticket_key="TEST-1",
            ticket_type=TicketType.FEATURE,
        )

        with (
            patch("forge.workflow.nodes.prd_generation.JiraClient", return_value=mock_jira),
            patch("forge.workflow.nodes.prd_generation.ForgeAgent", return_value=mock_agent),
            patch(
                "forge.workflow.nodes.prd_generation.post_status_comment",
                new_callable=AsyncMock,
            ),
            patch(
                "forge.workflow.nodes.error_handler.notify_error",
                new_callable=AsyncMock,
            ),
        ):
            result = await generate_prd(state)

        stage = _get_stage(result, STAGE_PRD)
        assert stage.get("started_at") is not None
        assert stage.get("ended_at") is not None
        assert result.get("last_error") is not None


# ---------------------------------------------------------------------------
# PRD regeneration stats tests
# ---------------------------------------------------------------------------


class TestRegeneratePrdStatsRecording:
    """Tests for stats recording in regenerate_prd_with_feedback node."""

    @pytest.mark.asyncio
    async def test_increments_revision_on_feedback(self):
        """regenerate_prd_with_feedback should increment iteration_count by 1."""
        from forge.workflow.nodes.prd_generation import regenerate_prd_with_feedback

        mock_jira = create_mock_jira()
        mock_agent = create_mock_agent()
        state = create_initial_feature_state(
            ticket_key="TEST-1",
            ticket_type=TicketType.FEATURE,
            prd_content="# Original PRD",
            feedback_comment="! Please add more detail about authentication",
        )

        with (
            patch(
                "forge.workflow.nodes.prd_generation.JiraClient",
                return_value=mock_jira,
            ),
            patch(
                "forge.workflow.nodes.prd_generation.ForgeAgent",
                return_value=mock_agent,
            ),
        ):
            result = await regenerate_prd_with_feedback(state)

        stage = _get_stage(result, STAGE_PRD)
        assert stage.get("iteration_count", 0) >= 1, "iteration_count must be incremented"

    @pytest.mark.asyncio
    async def test_records_stage_start_on_feedback(self):
        """regenerate_prd_with_feedback should set started_at on re-entry."""
        from forge.workflow.nodes.prd_generation import regenerate_prd_with_feedback

        mock_jira = create_mock_jira()
        mock_agent = create_mock_agent()
        state = create_initial_feature_state(
            ticket_key="TEST-1",
            ticket_type=TicketType.FEATURE,
            prd_content="# Original PRD",
            feedback_comment="! Needs more detail",
        )

        with (
            patch(
                "forge.workflow.nodes.prd_generation.JiraClient",
                return_value=mock_jira,
            ),
            patch(
                "forge.workflow.nodes.prd_generation.ForgeAgent",
                return_value=mock_agent,
            ),
        ):
            result = await regenerate_prd_with_feedback(state)

        stage = _get_stage(result, STAGE_PRD)
        assert stage.get("started_at") is not None

    @pytest.mark.asyncio
    async def test_records_stage_end_on_feedback(self):
        """regenerate_prd_with_feedback should record ended_at and machine_time."""
        from forge.workflow.nodes.prd_generation import regenerate_prd_with_feedback

        mock_jira = create_mock_jira()
        mock_agent = create_mock_agent()
        state = create_initial_feature_state(
            ticket_key="TEST-1",
            ticket_type=TicketType.FEATURE,
            prd_content="# Original PRD",
            feedback_comment="! Add more context",
        )

        with (
            patch(
                "forge.workflow.nodes.prd_generation.JiraClient",
                return_value=mock_jira,
            ),
            patch(
                "forge.workflow.nodes.prd_generation.ForgeAgent",
                return_value=mock_agent,
            ),
        ):
            result = await regenerate_prd_with_feedback(state)

        stage = _get_stage(result, STAGE_PRD)
        assert stage.get("ended_at") is not None
        assert stage.get("machine_time_seconds", 0.0) >= 0.0

    @pytest.mark.asyncio
    async def test_records_tokens_on_feedback(self):
        """regenerate_prd_with_feedback should record tokens for the revision."""
        from forge.workflow.nodes.prd_generation import regenerate_prd_with_feedback

        mock_jira = create_mock_jira()
        mock_agent = create_mock_agent()
        mock_agent.regenerate_with_feedback = AsyncMock(return_value="D" * 800)
        state = create_initial_feature_state(
            ticket_key="TEST-1",
            ticket_type=TicketType.FEATURE,
            prd_content="C" * 400,
            feedback_comment="! " + "E" * 40,
        )

        with (
            patch(
                "forge.workflow.nodes.prd_generation.JiraClient",
                return_value=mock_jira,
            ),
            patch(
                "forge.workflow.nodes.prd_generation.ForgeAgent",
                return_value=mock_agent,
            ),
        ):
            result = await regenerate_prd_with_feedback(state)

        stage = _get_stage(result, STAGE_PRD)
        assert stage.get("input_tokens", 0) > 0
        assert stage.get("output_tokens", 0) > 0

    @pytest.mark.asyncio
    async def test_no_feedback_returns_unchanged_state(self):
        """regenerate_prd_with_feedback with no feedback should return state unchanged."""
        from forge.workflow.nodes.prd_generation import regenerate_prd_with_feedback

        state = create_initial_feature_state(
            ticket_key="TEST-1",
            ticket_type=TicketType.FEATURE,
            prd_content="# Original PRD",
        )

        result = await regenerate_prd_with_feedback(state)

        # State returned unchanged — no stage_timestamps mutation
        assert result is state

    @pytest.mark.asyncio
    async def test_stats_recorded_on_exception(self):
        """regenerate_prd_with_feedback records stage_end even on exception."""
        from forge.workflow.nodes.prd_generation import regenerate_prd_with_feedback

        mock_jira = create_mock_jira()
        mock_agent = create_mock_agent()
        mock_agent.regenerate_with_feedback = AsyncMock(side_effect=RuntimeError("API error"))
        state = create_initial_feature_state(
            ticket_key="TEST-1",
            ticket_type=TicketType.FEATURE,
            prd_content="# Original PRD",
            feedback_comment="! Add more detail",
        )

        with (
            patch(
                "forge.workflow.nodes.prd_generation.JiraClient",
                return_value=mock_jira,
            ),
            patch(
                "forge.workflow.nodes.prd_generation.ForgeAgent",
                return_value=mock_agent,
            ),
            patch(
                "forge.workflow.nodes.error_handler.notify_error",
                new_callable=AsyncMock,
            ),
        ):
            result = await regenerate_prd_with_feedback(state)

        stage = _get_stage(result, STAGE_PRD)
        assert stage.get("ended_at") is not None
        assert result.get("last_error") is not None


# ---------------------------------------------------------------------------
# Spec generation stats tests
# ---------------------------------------------------------------------------


class TestGenerateSpecStatsRecording:
    """Tests for stats recording in generate_spec node."""

    @pytest.mark.asyncio
    async def test_records_stage_start_on_entry(self):
        """generate_spec should initialise the SPEC stage with a started_at timestamp."""
        from forge.workflow.nodes.spec_generation import generate_spec

        mock_jira = create_mock_jira()
        mock_agent = create_mock_agent()
        state = create_initial_feature_state(
            ticket_key="TEST-2",
            ticket_type=TicketType.FEATURE,
            prd_content="# Approved PRD",
        )

        with (
            patch("forge.workflow.nodes.spec_generation.JiraClient", return_value=mock_jira),
            patch("forge.workflow.nodes.spec_generation.ForgeAgent", return_value=mock_agent),
            patch(
                "forge.workflow.nodes.spec_generation.post_status_comment",
                new_callable=AsyncMock,
            ),
        ):
            result = await generate_spec(state)

        stage = _get_stage(result, STAGE_SPEC)
        assert stage, "stage_timestamps[STAGE_SPEC] should be populated"
        assert stage.get("started_at") is not None

    @pytest.mark.asyncio
    async def test_records_stage_end_with_machine_time(self):
        """generate_spec should populate ended_at and machine_time_seconds."""
        from forge.workflow.nodes.spec_generation import generate_spec

        mock_jira = create_mock_jira()
        mock_agent = create_mock_agent()
        state = create_initial_feature_state(
            ticket_key="TEST-2",
            ticket_type=TicketType.FEATURE,
            prd_content="# Approved PRD",
        )

        with (
            patch("forge.workflow.nodes.spec_generation.JiraClient", return_value=mock_jira),
            patch("forge.workflow.nodes.spec_generation.ForgeAgent", return_value=mock_agent),
            patch(
                "forge.workflow.nodes.spec_generation.post_status_comment",
                new_callable=AsyncMock,
            ),
        ):
            result = await generate_spec(state)

        stage = _get_stage(result, STAGE_SPEC)
        assert stage.get("ended_at") is not None
        assert stage.get("machine_time_seconds", 0.0) >= 0.0

    @pytest.mark.asyncio
    async def test_records_tokens_from_llm_response(self):
        """generate_spec should record non-zero token counts after LLM call."""
        from forge.workflow.nodes.spec_generation import generate_spec

        mock_jira = create_mock_jira()
        mock_agent = create_mock_agent(spec_content="F" * 800)
        state = create_initial_feature_state(
            ticket_key="TEST-2",
            ticket_type=TicketType.FEATURE,
            prd_content="G" * 400,
        )

        with (
            patch("forge.workflow.nodes.spec_generation.JiraClient", return_value=mock_jira),
            patch("forge.workflow.nodes.spec_generation.ForgeAgent", return_value=mock_agent),
            patch(
                "forge.workflow.nodes.spec_generation.post_status_comment",
                new_callable=AsyncMock,
            ),
        ):
            result = await generate_spec(state)

        stage = _get_stage(result, STAGE_SPEC)
        assert stage.get("input_tokens", 0) > 0
        assert stage.get("output_tokens", 0) > 0

    @pytest.mark.asyncio
    async def test_stats_recorded_on_missing_prd(self):
        """generate_spec should record stage_end even when PRD content is empty."""
        from forge.workflow.nodes.spec_generation import generate_spec

        # No prd_content in state, and Jira returns empty description
        mock_jira = create_mock_jira(description="")
        mock_agent = create_mock_agent()
        state = create_initial_feature_state(
            ticket_key="TEST-2",
            ticket_type=TicketType.FEATURE,
        )

        with (
            patch("forge.workflow.nodes.spec_generation.JiraClient", return_value=mock_jira),
            patch("forge.workflow.nodes.spec_generation.ForgeAgent", return_value=mock_agent),
            patch(
                "forge.workflow.nodes.spec_generation.post_status_comment",
                new_callable=AsyncMock,
            ),
        ):
            result = await generate_spec(state)

        stage = _get_stage(result, STAGE_SPEC)
        assert stage.get("started_at") is not None
        assert stage.get("ended_at") is not None

    @pytest.mark.asyncio
    async def test_stats_recorded_on_exception(self):
        """generate_spec should record stage_end even when an exception is raised."""
        from forge.workflow.nodes.spec_generation import generate_spec

        mock_jira = create_mock_jira()
        mock_agent = create_mock_agent()
        mock_agent.generate_spec = AsyncMock(side_effect=RuntimeError("Spec LLM failure"))
        state = create_initial_feature_state(
            ticket_key="TEST-2",
            ticket_type=TicketType.FEATURE,
            prd_content="# Approved PRD",
        )

        with (
            patch("forge.workflow.nodes.spec_generation.JiraClient", return_value=mock_jira),
            patch("forge.workflow.nodes.spec_generation.ForgeAgent", return_value=mock_agent),
            patch(
                "forge.workflow.nodes.spec_generation.post_status_comment",
                new_callable=AsyncMock,
            ),
            patch(
                "forge.workflow.nodes.error_handler.notify_error",
                new_callable=AsyncMock,
            ),
        ):
            result = await generate_spec(state)

        stage = _get_stage(result, STAGE_SPEC)
        assert stage.get("started_at") is not None
        assert stage.get("ended_at") is not None
        assert result.get("last_error") is not None


# ---------------------------------------------------------------------------
# Spec regeneration stats tests
# ---------------------------------------------------------------------------


class TestRegenerateSpecStatsRecording:
    """Tests for stats recording in regenerate_spec_with_feedback node."""

    @pytest.mark.asyncio
    async def test_increments_revision_on_feedback(self):
        """regenerate_spec_with_feedback should increment iteration_count."""
        from forge.workflow.nodes.spec_generation import regenerate_spec_with_feedback

        mock_jira = create_mock_jira()
        mock_agent = create_mock_agent()
        state = create_initial_feature_state(
            ticket_key="TEST-2",
            ticket_type=TicketType.FEATURE,
            spec_content="# Original Spec",
            feedback_comment="! Please add more Given/When/Then scenarios",
        )

        with (
            patch(
                "forge.workflow.nodes.spec_generation.JiraClient",
                return_value=mock_jira,
            ),
            patch(
                "forge.workflow.nodes.spec_generation.ForgeAgent",
                return_value=mock_agent,
            ),
        ):
            result = await regenerate_spec_with_feedback(state)

        stage = _get_stage(result, STAGE_SPEC)
        assert stage.get("iteration_count", 0) >= 1

    @pytest.mark.asyncio
    async def test_records_stage_start_on_feedback(self):
        """regenerate_spec_with_feedback should set started_at on re-entry."""
        from forge.workflow.nodes.spec_generation import regenerate_spec_with_feedback

        mock_jira = create_mock_jira()
        mock_agent = create_mock_agent()
        state = create_initial_feature_state(
            ticket_key="TEST-2",
            ticket_type=TicketType.FEATURE,
            spec_content="# Original Spec",
            feedback_comment="! Needs more detail",
        )

        with (
            patch(
                "forge.workflow.nodes.spec_generation.JiraClient",
                return_value=mock_jira,
            ),
            patch(
                "forge.workflow.nodes.spec_generation.ForgeAgent",
                return_value=mock_agent,
            ),
        ):
            result = await regenerate_spec_with_feedback(state)

        stage = _get_stage(result, STAGE_SPEC)
        assert stage.get("started_at") is not None

    @pytest.mark.asyncio
    async def test_records_stage_end_on_feedback(self):
        """regenerate_spec_with_feedback should record ended_at and machine_time."""
        from forge.workflow.nodes.spec_generation import regenerate_spec_with_feedback

        mock_jira = create_mock_jira()
        mock_agent = create_mock_agent()
        state = create_initial_feature_state(
            ticket_key="TEST-2",
            ticket_type=TicketType.FEATURE,
            spec_content="# Original Spec",
            feedback_comment="! Add edge cases",
        )

        with (
            patch(
                "forge.workflow.nodes.spec_generation.JiraClient",
                return_value=mock_jira,
            ),
            patch(
                "forge.workflow.nodes.spec_generation.ForgeAgent",
                return_value=mock_agent,
            ),
        ):
            result = await regenerate_spec_with_feedback(state)

        stage = _get_stage(result, STAGE_SPEC)
        assert stage.get("ended_at") is not None
        assert stage.get("machine_time_seconds", 0.0) >= 0.0

    @pytest.mark.asyncio
    async def test_records_tokens_on_feedback(self):
        """regenerate_spec_with_feedback should record tokens for the revision."""
        from forge.workflow.nodes.spec_generation import regenerate_spec_with_feedback

        mock_jira = create_mock_jira()
        mock_agent = create_mock_agent()
        mock_agent.regenerate_with_feedback = AsyncMock(return_value="H" * 800)
        state = create_initial_feature_state(
            ticket_key="TEST-2",
            ticket_type=TicketType.FEATURE,
            spec_content="I" * 400,
            feedback_comment="! " + "J" * 40,
        )

        with (
            patch(
                "forge.workflow.nodes.spec_generation.JiraClient",
                return_value=mock_jira,
            ),
            patch(
                "forge.workflow.nodes.spec_generation.ForgeAgent",
                return_value=mock_agent,
            ),
        ):
            result = await regenerate_spec_with_feedback(state)

        stage = _get_stage(result, STAGE_SPEC)
        assert stage.get("input_tokens", 0) > 0
        assert stage.get("output_tokens", 0) > 0

    @pytest.mark.asyncio
    async def test_no_feedback_returns_unchanged_state(self):
        """regenerate_spec_with_feedback with no feedback should return state unchanged."""
        from forge.workflow.nodes.spec_generation import regenerate_spec_with_feedback

        state = create_initial_feature_state(
            ticket_key="TEST-2",
            ticket_type=TicketType.FEATURE,
            spec_content="# Original Spec",
        )

        result = await regenerate_spec_with_feedback(state)

        assert result is state

    @pytest.mark.asyncio
    async def test_stats_recorded_on_exception(self):
        """regenerate_spec_with_feedback records stage_end even on exception."""
        from forge.workflow.nodes.spec_generation import regenerate_spec_with_feedback

        mock_jira = create_mock_jira()
        mock_agent = create_mock_agent()
        mock_agent.regenerate_with_feedback = AsyncMock(side_effect=RuntimeError("API error"))
        state = create_initial_feature_state(
            ticket_key="TEST-2",
            ticket_type=TicketType.FEATURE,
            spec_content="# Original Spec",
            feedback_comment="! Add more detail",
        )

        with (
            patch(
                "forge.workflow.nodes.spec_generation.JiraClient",
                return_value=mock_jira,
            ),
            patch(
                "forge.workflow.nodes.spec_generation.ForgeAgent",
                return_value=mock_agent,
            ),
            patch(
                "forge.workflow.nodes.error_handler.notify_error",
                new_callable=AsyncMock,
            ),
        ):
            result = await regenerate_spec_with_feedback(state)

        stage = _get_stage(result, STAGE_SPEC)
        assert stage.get("ended_at") is not None
        assert result.get("last_error") is not None


# ---------------------------------------------------------------------------
# Token estimation helper tests
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    """Tests for the _estimate_tokens helper."""

    def test_empty_string_returns_one(self):
        from forge.workflow.nodes.prd_generation import _estimate_tokens

        assert _estimate_tokens("") == 1

    def test_four_chars_returns_one(self):
        from forge.workflow.nodes.prd_generation import _estimate_tokens

        assert _estimate_tokens("abcd") == 1

    def test_estimate_scales_with_length(self):
        from forge.workflow.nodes.prd_generation import _estimate_tokens

        assert _estimate_tokens("a" * 400) == 100

    def test_spec_module_helper_matches(self):
        from forge.workflow.nodes.prd_generation import _estimate_tokens as prd_est
        from forge.workflow.nodes.spec_generation import _estimate_tokens as spec_est

        text = "Hello world test"
        assert prd_est(text) == spec_est(text)
