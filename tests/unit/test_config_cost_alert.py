"""Tests for stats cost alert threshold configuration settings."""

import pytest

from forge.config import Settings


REQUIRED_SETTINGS = dict(
    jira_base_url="https://test.atlassian.net",
    jira_api_token="test",
    jira_user_email="test@example.com",
    github_token="test",
    anthropic_api_key="test",
)


class TestStatsCostAlertConfig:
    def test_default_cost_alert_enabled_is_true(self):
        settings = Settings(**REQUIRED_SETTINGS)
        assert settings.stats_cost_alert_enabled is True

    def test_default_cost_alert_threshold_tokens(self):
        settings = Settings(**REQUIRED_SETTINGS)
        assert settings.stats_cost_alert_threshold_tokens == 1_000_000

    def test_cost_alert_enabled_can_be_disabled(self):
        settings = Settings(**REQUIRED_SETTINGS, stats_cost_alert_enabled=False)
        assert settings.stats_cost_alert_enabled is False

    def test_cost_alert_threshold_can_be_customized(self):
        settings = Settings(**REQUIRED_SETTINGS, stats_cost_alert_threshold_tokens=500_000)
        assert settings.stats_cost_alert_threshold_tokens == 500_000

    def test_cost_alert_threshold_accepts_large_values(self):
        settings = Settings(**REQUIRED_SETTINGS, stats_cost_alert_threshold_tokens=10_000_000)
        assert settings.stats_cost_alert_threshold_tokens == 10_000_000

    def test_cost_alert_threshold_is_int(self):
        settings = Settings(**REQUIRED_SETTINGS)
        assert isinstance(settings.stats_cost_alert_threshold_tokens, int)

    def test_cost_alert_enabled_is_bool(self):
        settings = Settings(**REQUIRED_SETTINGS)
        assert isinstance(settings.stats_cost_alert_enabled, bool)
