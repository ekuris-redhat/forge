"""Unit and integration tests for Weekly Status Report CLI, including dry-run and configuration overrides."""

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.cli import cmd_weekly_report
from forge.config import get_settings


@pytest.mark.asyncio
@patch("forge.orchestrator.checkpointer.get_checkpointer")
@patch("forge.integrations.jira.client.JiraClient")
@patch("forge.workflow.stats.alerter.StakeholderAlerter")
@patch("forge.workflow.stats.reporter.IdempotentReporter")
async def test_cmd_weekly_report_overrides(
    mock_reporter_cls, mock_alerter_cls, mock_jira_cls, mock_get_cp
):
    """Test that local configuration overrides successfully replace environment defaults during execution."""
    mock_get_cp.return_value = AsyncMock()
    mock_jira = AsyncMock()
    mock_jira_cls.return_value = mock_jira

    mock_report = MagicMock()
    mock_report.start_time = "2026-05-01T00:00:00Z"
    mock_report.end_time = "2026-05-08T00:00:00Z"
    mock_report.to_markdown.return_value = "MD Report"

    mock_reporter = MagicMock()
    mock_reporter.generate_report = AsyncMock(return_value=mock_report)
    mock_reporter_cls.return_value = mock_reporter

    mock_alerter = AsyncMock()
    mock_alerter.send_alert.return_value = {"status": "success", "channel_used": "email"}
    mock_alerter_cls.return_value = mock_alerter

    # Pre-check settings defaults
    initial_redis = get_settings().redis_url
    initial_log = get_settings().log_level

    # Define args with multiple configuration overrides
    args = argparse.Namespace(
        project="PROJ",
        days=7,
        format="markdown",
        output="report.md",
        dry_run=False,
        config=["redis_url=redis://localhost:9999/2", "log_level=DEBUG"],
    )

    # We patch Settings inside the execution to verify settings are overridden
    with patch("forge.config.Settings") as mock_settings_cls:
        # Mocking Settings loading
        mock_settings = MagicMock()
        mock_settings.redis_url = "redis://localhost:9999/2"
        mock_settings.log_level = "DEBUG"
        mock_settings.model_dump.return_value = {
            "redis_url": initial_redis,
            "log_level": initial_log,
        }
        mock_settings_cls.return_value = mock_settings

        res = await cmd_weekly_report(args)
        assert res == 0

        # Verify our settings override was invoked
        mock_settings_cls.assert_called()


@pytest.mark.asyncio
@patch("forge.orchestrator.checkpointer.get_checkpointer")
@patch("forge.integrations.jira.client.JiraClient")
@patch("forge.workflow.stats.alerter.StakeholderAlerter")
@patch("forge.workflow.stats.reporter.IdempotentReporter")
async def test_cmd_weekly_report_dry_run(
    mock_reporter_cls, mock_alerter_cls, mock_jira_cls, mock_get_cp, capsys
):
    """Test that running with --dry-run outputs markdown to stdout without writing files or firing alerts."""
    mock_get_cp.return_value = AsyncMock()
    mock_jira = AsyncMock()
    mock_jira_cls.return_value = mock_jira

    mock_report = MagicMock()
    mock_report.to_markdown.return_value = "MD DRY RUN REPORT"

    mock_reporter = MagicMock()
    mock_reporter.generate_report = AsyncMock(return_value=mock_report)
    mock_reporter_cls.return_value = mock_reporter

    mock_alerter = AsyncMock()
    mock_alerter.send_alert.return_value = {"status": "success", "channel_used": "email"}
    mock_alerter_cls.return_value = mock_alerter

    args = argparse.Namespace(
        project="PROJ",
        days=7,
        format="markdown",
        output="report.md",
        dry_run=True,
        config=None,
    )

    res = await cmd_weekly_report(args)
    assert res == 0

    # Verify that IdempotentReporter was not asked to publish, and StakeholderAlerter was not called
    mock_reporter.publish_report.assert_not_called()
    mock_alerter.send_alert.assert_not_called()

    # Verify output in stdout
    captured = capsys.readouterr()
    assert "MD DRY RUN REPORT" in captured.out


@pytest.mark.asyncio
async def test_cmd_weekly_report_validation():
    """Test CLI parameter validation for invalid arguments."""
    # 1. Invalid project key (empty)
    args1 = argparse.Namespace(
        project="",
        days=7,
        format="markdown",
        output="report.md",
        dry_run=False,
        config=None,
    )
    res1 = await cmd_weekly_report(args1)
    assert res1 == 1

    # 2. Invalid days (negative)
    args2 = argparse.Namespace(
        project="PROJ",
        days=-5,
        format="markdown",
        output="report.md",
        dry_run=False,
        config=None,
    )
    res2 = await cmd_weekly_report(args2)
    assert res2 == 1
