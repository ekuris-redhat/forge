"""Tests for checked-in Grafana dashboard assets."""

import json
from pathlib import Path

GRAFANA_DIR = Path("devtools/grafana")
DASHBOARD_DIR = GRAFANA_DIR / "dashboards"


def test_grafana_dashboard_json_is_valid() -> None:
    dashboards = sorted(DASHBOARD_DIR.glob("*.json"))
    assert dashboards, "expected checked-in Grafana dashboards"

    for dashboard in dashboards:
        data = json.loads(dashboard.read_text())
        assert data["kind"] == "Dashboard"
        assert data["spec"]["title"]


def test_dashboards_use_configurable_trace_fields() -> None:
    joined = "\n".join(path.read_text() for path in sorted(DASHBOARD_DIR.glob("*.json")))

    assert "OSASINFRA" not in joined
    assert "OSPA" not in joined
    assert "tags[1]" not in joined
    assert "tags[3]" not in joined
    assert "project_id=~" not in joined
    assert "metadata['project_id']" in joined
    assert "metadata['ticket_type']" in joined
    assert "metadata['workflow_step']" in joined


def test_grafana_provisioning_files_exist() -> None:
    assert (GRAFANA_DIR / "provisioning/dashboards/dashboards.yml").is_file()
    assert (GRAFANA_DIR / "provisioning/datasources/clickhouse.yml").is_file()
    assert (GRAFANA_DIR / "provisioning/datasources/prometheus.yml").is_file()
    assert (GRAFANA_DIR / "provisioning/datasources/redis.yml").is_file()
    assert (GRAFANA_DIR / "compose.grafana.yml").is_file()
    assert (GRAFANA_DIR / "compose.langfuse-network.yml").is_file()
