"""Unit tests for StakeholderAlerter alerting engine and channel fallbacks."""

import os
from unittest.mock import patch

import pytest

from forge.config import Settings
from forge.workflow.stats.alerter import StakeholderAlerter
from forge.workflow.stats.reporter import TokenUsage, WeeklyReportMetrics


@pytest.fixture
def mock_report():
    """Create a mock WeeklyReportMetrics object."""
    return WeeklyReportMetrics(
        project_key="PROJ",
        window_days=7,
        start_time="2026-05-01T00:00:00Z",
        end_time="2026-05-08T00:00:00Z",
        active_tickets=["PROJ-101"],
        total_duration_seconds=3600.0,
        phase_durations={"prd_generation": 3600.0},
        token_usage=TokenUsage(input=5000, output=3000, total=8000),
        total_cost=0.50,
        tickets={},
    )


def test_alerter_resolve_fallback_chain():
    """Test resolution of primary and fallback alert chains."""
    settings = Settings(
        jira_base_url="https://company.atlassian.net",
        jira_api_token="token",
        jira_user_email="user@company.com",
        github_token="gh-token",
    )

    # 1. Default alert channel (email)
    alerter = StakeholderAlerter(settings)
    assert alerter.resolve_alert_chain() == ["email", "slack", "webhook"]

    # 2. Configured custom primary (slack)
    with patch.dict(os.environ, {"FORGE_ALERT_CHANNEL": "slack"}):
        assert alerter.resolve_alert_chain() == ["slack", "email", "webhook"]

    # 3. Configured custom primary (webhook)
    with patch.dict(os.environ, {"FORGE_ALERT_CHANNEL": "webhook"}):
        assert alerter.resolve_alert_chain() == ["webhook", "email", "slack"]


def test_alerter_configured_channels():
    """Test resolution of configured alert channels from environment."""
    settings = Settings(
        jira_base_url="https://company.atlassian.net",
        jira_api_token="token",
        jira_user_email="user@company.com",
        github_token="gh-token",
    )
    alerter = StakeholderAlerter(settings)

    # Clean env mapping
    with patch.dict(os.environ, {}, clear=True):
        assert alerter.get_configured_channels() == {}

        # Set specific ones
        env_overrides = {
            "FORGE_ALERT_EMAIL": "test@example.com",
            "FORGE_SLACK_WEBHOOK": "https://hooks.slack.com/services/abc",
            "FORGE_WEBHOOK_URL": "https://callback.com/webhook",
        }
        with patch.dict(os.environ, env_overrides):
            configured = alerter.get_configured_channels()
            assert configured["email"] == "test@example.com"
            assert configured["slack"] == "https://hooks.slack.com/services/abc"
            assert configured["webhook"] == "https://callback.com/webhook"


@pytest.mark.asyncio
async def test_alerter_send_alert_success(mock_report):
    """Test sending alerts successfully through the primary/fallback channels."""
    settings = Settings(
        jira_base_url="https://company.atlassian.net",
        jira_api_token="token",
        jira_user_email="user@company.com",
        github_token="gh-token",
    )
    alerter = StakeholderAlerter(settings)

    # Mock success of primary (email)
    env_overrides = {
        "FORGE_ALERT_CHANNEL": "email",
        "FORGE_ALERT_EMAIL": "team@company.com",
    }
    with patch.dict(os.environ, env_overrides, clear=True):
        res = await alerter.send_alert(mock_report, report_path="report.md")
        assert res["sent_successfully"] is True
        assert res["channel_used"] == "email"
        assert res["results"]["email"]["status"] == "success"

    # Mock success of fallback when primary is unconfigured (slack)
    env_overrides_fallback = {
        "FORGE_ALERT_CHANNEL": "email",  # primary is email, but unconfigured
        "FORGE_SLACK_WEBHOOK": "https://slack.com/hook",
    }
    with patch.dict(os.environ, env_overrides_fallback, clear=True):
        res = await alerter.send_alert(mock_report, report_path="report.md")
        assert res["sent_successfully"] is True
        assert res["channel_used"] == "slack"
        assert res["results"]["email"]["status"] == "unconfigured"
        assert res["results"]["slack"]["status"] == "success"


@pytest.mark.asyncio
async def test_alerter_no_channels_configured_raises(mock_report):
    """Test that alerter raises ValueError if no alert channels are configured."""
    settings = Settings(
        jira_base_url="https://company.atlassian.net",
        jira_api_token="token",
        jira_user_email="user@company.com",
        github_token="gh-token",
    )
    alerter = StakeholderAlerter(settings)

    with (
        patch.dict(os.environ, {}, clear=True),
        pytest.raises(ValueError, match="No alert channels configured"),
    ):
        await alerter.send_alert(mock_report)
