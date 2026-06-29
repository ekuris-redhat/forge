"""Unit tests for metrics endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

from forge.main import app


class TestMetricsEndpoint:
    """Tests for /metrics endpoint."""

    @pytest.mark.asyncio
    async def test_metrics_returns_200(self):
        """Metrics endpoint returns 200."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/metrics")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_metrics_returns_prometheus_format(self):
        """Metrics endpoint returns Prometheus format."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/metrics")

        content_type = response.headers.get("content-type", "")
        assert "text/plain" in content_type or "openmetrics" in content_type

    @pytest.mark.asyncio
    async def test_metrics_includes_forge_metrics(self):
        """Metrics includes forge-related counters."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/metrics")

        body = response.text
        # Should include forge metrics
        assert "forge" in body

    @pytest.mark.asyncio
    async def test_metrics_includes_workflow_metrics(self):
        """Metrics includes workflow-related counters."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/metrics")

        body = response.text
        # Should include forge workflow metrics
        assert "forge_workflows" in body


class TestMetricRegistration:
    """Tests for metric registration."""

    def test_webhook_counter_exists(self):
        """Webhook received counter is registered."""
        from forge.api.routes.metrics import WEBHOOKS_RECEIVED

        assert WEBHOOKS_RECEIVED is not None

    def test_webhook_counter_has_labels(self):
        """Webhook counter has source and event_type labels."""
        from forge.api.routes.metrics import WEBHOOKS_RECEIVED

        # Counter should be labelable
        labeled = WEBHOOKS_RECEIVED.labels(source="jira", event_type="issue_updated")
        assert labeled is not None

    def test_workflow_histogram_exists(self):
        """Agent duration histogram is registered."""
        from forge.api.routes.metrics import AGENT_DURATION

        assert AGENT_DURATION is not None

    def test_increment_webhook_counter(self):
        """Can increment webhook counter."""
        from forge.api.routes.metrics import WEBHOOKS_RECEIVED

        # Should not raise
        WEBHOOKS_RECEIVED.labels(source="github", event_type="check_run").inc()
