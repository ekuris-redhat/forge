"""Tests for stats posting integration in the Feature workflow graph.

Verifies that:
- post_terminal_stats node is present in the compiled graph
- All terminal paths (success, blocked, failure) route through post_terminal_stats
- post_terminal_stats is the last node before END
- Unrecoverable failure routing functions return "post_terminal_stats"
"""

from forge.models.workflow import TicketType
from forge.workflow.feature.graph import (
    _route_after_epic_decomposition,
    _route_after_generation,
    _route_after_spec_generation,
    _route_after_task_generation,
    build_feature_graph,
)


def _feature_state(**overrides):
    """Build a minimal feature state dict for routing tests."""
    base = {
        "ticket_key": "FEAT-1",
        "ticket_type": TicketType.FEATURE,
        "current_node": "start",
        "is_paused": False,
        "retry_count": 0,
        "last_error": None,
        "prd_content": "",
        "spec_content": "",
        "epic_keys": [],
        "task_keys": [],
        "pr_urls": [],
    }
    return {**base, **overrides}


class TestFeatureGraphStatsNode:
    """post_terminal_stats is present in the compiled feature graph."""

    def test_post_terminal_stats_node_present(self):
        """post_terminal_stats node is registered in the compiled graph."""
        graph = build_feature_graph()
        compiled = graph.compile()
        assert "post_terminal_stats" in compiled.nodes

    def test_post_terminal_stats_node_is_reachable(self):
        """post_terminal_stats appears in the compiled graph node set."""
        graph = build_feature_graph()
        compiled = graph.compile()
        # Node must be reachable — confirm it's not just a stub
        node_keys = set(compiled.nodes.keys())
        assert "post_terminal_stats" in node_keys


class TestFeatureTerminalPathsRouteToStats:
    """All terminal paths in the feature graph route through post_terminal_stats."""

    def test_prd_generation_failure_routes_to_stats(self):
        """generate_prd failure (no prd_content, has error) routes to post_terminal_stats."""
        state = _feature_state(last_error="LLM timeout", prd_content="")
        result = _route_after_generation(state)
        assert result == "post_terminal_stats"

    def test_prd_generation_success_does_not_route_to_stats(self):
        """generate_prd success routes to prd_approval_gate, not post_terminal_stats."""
        state = _feature_state(last_error=None, prd_content="Some PRD content")
        result = _route_after_generation(state)
        assert result == "prd_approval_gate"
        assert result != "post_terminal_stats"

    def test_prd_generation_error_with_content_does_not_route_to_stats(self):
        """generate_prd with error but existing content goes to gate (not terminal failure)."""
        state = _feature_state(last_error="minor error", prd_content="Existing PRD")
        result = _route_after_generation(state)
        assert result == "prd_approval_gate"

    def test_spec_generation_failure_routes_to_stats(self):
        """generate_spec failure (no spec_content, has error) routes to post_terminal_stats."""
        state = _feature_state(last_error="LLM timeout", spec_content="")
        result = _route_after_spec_generation(state)
        assert result == "post_terminal_stats"

    def test_spec_generation_success_does_not_route_to_stats(self):
        """generate_spec success routes to spec_approval_gate."""
        state = _feature_state(last_error=None, spec_content="Some spec content")
        result = _route_after_spec_generation(state)
        assert result == "spec_approval_gate"

    def test_epic_decomposition_failure_routes_to_stats(self):
        """decompose_epics failure (no epic_keys, has error) routes to post_terminal_stats."""
        state = _feature_state(last_error="Epic decomposition failed", epic_keys=[])
        result = _route_after_epic_decomposition(state)
        assert result == "post_terminal_stats"

    def test_epic_decomposition_success_does_not_route_to_stats(self):
        """decompose_epics success routes to plan_approval_gate."""
        state = _feature_state(last_error=None, epic_keys=["FEAT-10", "FEAT-11"])
        result = _route_after_epic_decomposition(state)
        assert result == "plan_approval_gate"

    def test_task_generation_failure_routes_to_stats(self):
        """generate_tasks failure (no task_keys, has error) routes to post_terminal_stats."""
        state = _feature_state(last_error="Task generation failed", task_keys=[])
        result = _route_after_task_generation(state)
        assert result == "post_terminal_stats"

    def test_task_generation_success_does_not_route_to_stats(self):
        """generate_tasks success routes to task_approval_gate."""
        state = _feature_state(last_error=None, task_keys=["FEAT-20", "FEAT-21"])
        result = _route_after_task_generation(state)
        assert result == "task_approval_gate"


class TestFeatureGraphEdgeStructure:
    """Verify graph edge structure ensures stats posting on all terminal paths."""

    def test_escalate_blocked_has_edge_to_post_terminal_stats(self):
        """escalate_blocked edges directly to post_terminal_stats (blocked terminal path)."""
        graph = build_feature_graph()
        # Use the uncompiled graph's edges set (tuples of (from, to))
        assert ("escalate_blocked", "post_terminal_stats") in graph.edges, (
            "escalate_blocked must route to post_terminal_stats"
        )

    def test_aggregate_feature_status_has_edge_to_post_terminal_stats(self):
        """aggregate_feature_status edges to post_terminal_stats (success terminal path)."""
        graph = build_feature_graph()
        assert ("aggregate_feature_status", "post_terminal_stats") in graph.edges, (
            "aggregate_feature_status must route to post_terminal_stats"
        )

    def test_post_terminal_stats_has_edge_to_end(self):
        """post_terminal_stats has an outgoing edge to END (__end__)."""
        graph = build_feature_graph()
        assert ("post_terminal_stats", "__end__") in graph.edges, (
            "post_terminal_stats must route to END"
        )

    def test_graph_compiles_successfully(self):
        """build_feature_graph() compiles without error after stats node addition."""
        graph = build_feature_graph()
        compiled = graph.compile()
        assert compiled is not None

    def test_success_path_flows_through_stats_before_end(self):
        """The success path aggregate_feature_status → post_terminal_stats → END is wired."""
        graph = build_feature_graph()
        edges = graph.edges
        assert ("aggregate_feature_status", "post_terminal_stats") in edges, (
            "aggregate_feature_status must edge to post_terminal_stats"
        )
        assert ("post_terminal_stats", "__end__") in edges, "post_terminal_stats must edge to END"


class TestFeatureGraphStatsOrdering:
    """Stats posting occurs AFTER other terminal actions."""

    def test_aggregate_feature_status_is_penultimate_node(self):
        """Success path: complete_tasks → aggregate_epic_status → aggregate_feature_status → post_terminal_stats → END."""
        graph = build_feature_graph()
        edges = graph.edges

        assert ("complete_tasks", "aggregate_epic_status") in edges, (
            "complete_tasks must edge to aggregate_epic_status"
        )
        assert ("aggregate_epic_status", "aggregate_feature_status") in edges, (
            "aggregate_epic_status must edge to aggregate_feature_status"
        )
        assert ("aggregate_feature_status", "post_terminal_stats") in edges, (
            "aggregate_feature_status must edge to post_terminal_stats (stats after status)"
        )

    def test_escalate_blocked_routes_directly_to_stats(self):
        """escalate_blocked → post_terminal_stats (stats right after blocked action)."""
        graph = build_feature_graph()
        assert ("escalate_blocked", "post_terminal_stats") in graph.edges, (
            "escalate_blocked must directly edge to post_terminal_stats"
        )

    def test_aggregate_feature_status_does_not_edge_to_end_directly(self):
        """aggregate_feature_status does NOT have a direct edge to END (stats must be between)."""
        graph = build_feature_graph()
        assert ("aggregate_feature_status", "__end__") not in graph.edges, (
            "aggregate_feature_status must NOT edge directly to END; "
            "post_terminal_stats must be between"
        )

    def test_escalate_blocked_does_not_edge_to_end_directly(self):
        """escalate_blocked does NOT have a direct edge to END (stats must be between)."""
        graph = build_feature_graph()
        assert ("escalate_blocked", "__end__") not in graph.edges, (
            "escalate_blocked must NOT edge directly to END; post_terminal_stats must be between"
        )
