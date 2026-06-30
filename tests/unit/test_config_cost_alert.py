"""Tests for stats cost alert threshold configuration settings."""

import json

from forge.config import Settings

REQUIRED_SETTINGS = {
    "jira_base_url": "https://test.atlassian.net",
    "jira_api_token": "test",
    "jira_user_email": "test@example.com",
    "github_token": "test",
    "anthropic_api_key": "test",
}


class TestStatsCostAlertConfig:
    def test_default_cost_alert_enabled_is_true(self):
        settings = Settings(**REQUIRED_SETTINGS)
        assert settings.stats_alert_enabled is True

    def test_default_cost_alert_threshold_tokens(self):
        settings = Settings(**REQUIRED_SETTINGS)
        assert settings.stats_alert_threshold_tokens == 1_000_000

    def test_cost_alert_enabled_can_be_disabled(self):
        settings = Settings(**REQUIRED_SETTINGS, stats_alert_enabled=False)
        assert settings.stats_alert_enabled is False

    def test_cost_alert_threshold_can_be_customized(self):
        settings = Settings(**REQUIRED_SETTINGS, stats_alert_threshold_tokens=500_000)
        assert settings.stats_alert_threshold_tokens == 500_000

    def test_cost_alert_threshold_accepts_large_values(self):
        settings = Settings(**REQUIRED_SETTINGS, stats_alert_threshold_tokens=10_000_000)
        assert settings.stats_alert_threshold_tokens == 10_000_000

    def test_cost_alert_threshold_is_int(self):
        settings = Settings(**REQUIRED_SETTINGS)
        assert isinstance(settings.stats_alert_threshold_tokens, int)

    def test_cost_alert_enabled_is_bool(self):
        settings = Settings(**REQUIRED_SETTINGS)
        assert isinstance(settings.stats_alert_enabled, bool)


class TestStatsCostAlertDollarThreshold:
    """Tests for the new stats_alert_threshold_cost setting."""

    def test_default_dollar_threshold_is_none(self):
        settings = Settings(**REQUIRED_SETTINGS)
        assert settings.stats_alert_threshold_cost is None

    def test_dollar_threshold_can_be_set(self):
        settings = Settings(**REQUIRED_SETTINGS, stats_alert_threshold_cost=10.0)
        assert settings.stats_alert_threshold_cost == 10.0

    def test_dollar_threshold_accepts_small_values(self):
        settings = Settings(**REQUIRED_SETTINGS, stats_alert_threshold_cost=0.01)
        assert settings.stats_alert_threshold_cost == 0.01

    def test_dollar_threshold_is_float_when_set(self):
        settings = Settings(**REQUIRED_SETTINGS, stats_alert_threshold_cost=5.0)
        assert isinstance(settings.stats_alert_threshold_cost, float)


class TestLLMPricingConfig:
    """Tests for the llm_pricing configuration field."""

    def test_default_pricing_contains_claude_sonnet_4(self):
        settings = Settings(**REQUIRED_SETTINGS)
        assert "claude-sonnet-4" in settings.llm_pricing

    def test_default_pricing_contains_claude_opus_4(self):
        settings = Settings(**REQUIRED_SETTINGS)
        assert "claude-opus-4" in settings.llm_pricing

    def test_default_pricing_contains_gemini_models(self):
        settings = Settings(**REQUIRED_SETTINGS)
        assert "gemini-2.5-flash" in settings.llm_pricing

    def test_default_pricing_has_input_and_output_rates(self):
        settings = Settings(**REQUIRED_SETTINGS)
        for key, rates in settings.llm_pricing.items():
            assert "input" in rates, f"Missing 'input' rate for {key}"
            assert "output" in rates, f"Missing 'output' rate for {key}"

    def test_pricing_rates_are_floats(self):
        settings = Settings(**REQUIRED_SETTINGS)
        for key, rates in settings.llm_pricing.items():
            assert isinstance(rates["input"], float), f"Input rate for {key} is not float"
            assert isinstance(rates["output"], float), f"Output rate for {key} is not float"

    def test_custom_pricing_via_direct_field(self):
        custom = {"my-model": {"input": 1.0, "output": 2.0}}
        settings = Settings(**REQUIRED_SETTINGS, llm_pricing=custom)
        assert settings.llm_pricing == custom

    def test_pricing_is_dict(self):
        settings = Settings(**REQUIRED_SETTINGS)
        assert isinstance(settings.llm_pricing, dict)

    def test_custom_pricing_from_json_string(self, monkeypatch):
        """Pricing can be loaded from a JSON-encoded env var."""
        custom = {"test-model": {"input": 5.0, "output": 10.0}}
        monkeypatch.setenv("LLM_PRICING", json.dumps(custom))
        settings = Settings(**REQUIRED_SETTINGS)
        assert settings.llm_pricing == custom

    def test_default_claude_sonnet_4_rates(self):
        settings = Settings(**REQUIRED_SETTINGS)
        rates = settings.llm_pricing["claude-sonnet-4"]
        assert rates["input"] == 3.00
        assert rates["output"] == 15.00

    def test_default_claude_opus_4_rates(self):
        settings = Settings(**REQUIRED_SETTINGS)
        rates = settings.llm_pricing["claude-opus-4"]
        assert rates["input"] == 15.00
        assert rates["output"] == 75.00
