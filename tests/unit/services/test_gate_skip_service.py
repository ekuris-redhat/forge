"""Unit tests for PR Gate Skip settings persistence store."""

from datetime import datetime
from unittest.mock import patch

import pytest

from forge.config import Settings
from forge.models.gate_skip import PRGateSkipSettings
from forge.services.gate_skip_service import GateSkipService, get_skip_status, set_skip_status


@pytest.mark.asyncio
async def test_gate_skip_service_basic_flow(tmp_path) -> None:
    """Test setting, getting, and updating gate-skipping configurations."""
    # Set up a temporary database file
    db_file = tmp_path / "test_forge.db"

    # Patch settings to use the temporary database
    test_settings = Settings(
        redis_url="redis://localhost:6379/0",
        jira_base_url="https://test.atlassian.net",
        jira_api_token="test-token",
        jira_user_email="test@example.com",
        jira_webhook_secret="test-webhook-secret",
        github_token="test-github-token",
        github_webhook_secret="test-github-webhook-secret",
        anthropic_api_key="test-anthropic-key",
        database_path=str(db_file),
    )

    with patch("forge.services.gate_skip_service.get_settings", return_value=test_settings):
        # Reset initialization state of the service to force db creation
        GateSkipService._initialized = False

        # Initially, skip status should be False
        status = await get_skip_status("owner/repo", 1)
        assert status is False

        # Set skip status to True
        await set_skip_status("owner/repo", 1, True, "test-user")

        # Verify it is now True
        status = await get_skip_status("owner/repo", 1)
        assert status is True

        # Retrieve full settings
        settings_obj = await GateSkipService.get_skip_settings("owner/repo", 1)
        assert settings_obj is not None
        assert settings_obj.repo == "owner/repo"
        assert settings_obj.pr_number == 1
        assert settings_obj.skip_gate is True
        assert settings_obj.updated_by == "test-user"
        assert isinstance(settings_obj.updated_at, datetime)

        # Update skip status to False
        await set_skip_status("owner/repo", 1, False, "another-user")

        # Verify it is now False
        status = await get_skip_status("owner/repo", 1)
        assert status is False

        # Check settings again
        settings_obj = await GateSkipService.get_skip_settings("owner/repo", 1)
        assert settings_obj is not None
        assert settings_obj.skip_gate is False
        assert settings_obj.updated_by == "another-user"


def test_pr_gate_skip_settings_model() -> None:
    """Test direct instantiation and attributes of the model."""
    now = datetime.utcnow()
    settings = PRGateSkipSettings(
        repo="org/repo",
        pr_number=42,
        skip_gate=True,
        updated_by="alice",
        updated_at=now,
    )
    assert settings.repo == "org/repo"
    assert settings.pr_number == 42
    assert settings.skip_gate is True
    assert settings.updated_by == "alice"
    assert settings.updated_at == now


@pytest.mark.asyncio
async def test_evaluate_ci_status_skips_when_database_flag_set() -> None:
    """Test that evaluate_ci_status skips checking when database skip_gate flag is True."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from tests.fixtures.workflow_states import make_workflow_state

    from forge.workflow.nodes.ci_evaluator import evaluate_ci_status

    state = make_workflow_state(
        current_node="ci_evaluator",
        pr_urls=["https://github.com/org/repo/pull/42"],
        ci_skipped_checks=[],  # No skipped checks in state!
    )

    # Set skip status in database to True
    await set_skip_status("org/repo", 42, True, "test-user")

    mock_github = MagicMock()
    # It shouldn't even fetch the check runs because we skip!
    mock_github.get_pull_request = AsyncMock(return_value={"head": {"sha": "abc"}})
    mock_github.close = AsyncMock()

    with patch("forge.workflow.nodes.ci_evaluator.GitHubClient", return_value=mock_github):
        result = await evaluate_ci_status(state)

    # It should have passed CI because the database override skipped the gate
    assert result["ci_status"] == "passed"
