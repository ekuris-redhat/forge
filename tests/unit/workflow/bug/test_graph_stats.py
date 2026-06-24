"""Tests for stats posting integration in the Bug workflow graph.

Verifies that post_terminal_stats is wired into the bug graph at all terminal
paths: successful post-merge completion and blocked escalation.
"""

from forge.models.workflow import TicketType
from forge.workflow.bug.graph import build_bug_graph


def _bug_state(**overrides):
    """Build a minimal bug state dict for routing tests."""
    base = {
        "ticket_key": "BUG-1",
        "ticket_type": TicketType.BUG,
        "current_node": "start",
        "is_paused": False,
        "retry_count": 0,
        "last_error": None,
        "pr_merged": False,
    }
    return {**base, **overrides}


class TestBugGraphStatsNode:
    """post_terminal_stats is present in the compiled bug graph."""

    def test_post_terminal_stats_node_present(self):
        """post_terminal_stats node is registered in the compiled graph."""
        graph = build_bug_graph()
        compiled = graph.compile()
        assert "post_terminal_stats" in compiled.nodes

    def test_graph_compiles_with_stats_node(self):
        """Bug graph compiles without error after stats node integration."""
        graph = build_bug_graph()
        compiled = graph.compile()
        assert compiled is not None


class TestBugGraphTerminalEdges:
    """All terminal paths in the bug graph route through post_terminal_stats."""

    def test_post_merge_summary_routes_to_stats(self):
        """post_merge_summary → post_terminal_stats edge exists (success path)."""
        graph = build_bug_graph()
        assert ("post_merge_summary", "post_terminal_stats") in graph.edges, (
            "post_merge_summary must route to post_terminal_stats"
        )

    def test_escalate_blocked_routes_to_stats(self):
        """escalate_blocked → post_terminal_stats edge exists (blocked path)."""
        graph = build_bug_graph()
        assert ("escalate_blocked", "post_terminal_stats") in graph.edges, (
            "escalate_blocked must route to post_terminal_stats"
        )

    def test_post_terminal_stats_routes_to_end(self):
        """post_terminal_stats → __end__ edge exists."""
        graph = build_bug_graph()
        assert ("post_terminal_stats", "__end__") in graph.edges, (
            "post_terminal_stats must route to END"
        )

    def test_post_merge_summary_does_not_route_directly_to_end(self):
        """post_merge_summary does NOT have a direct edge to END (stats must be between)."""
        graph = build_bug_graph()
        assert ("post_merge_summary", "__end__") not in graph.edges, (
            "post_merge_summary must NOT edge directly to END; post_terminal_stats must be between"
        )

    def test_escalate_blocked_does_not_route_directly_to_end(self):
        """escalate_blocked does NOT have a direct edge to END (stats must be between)."""
        graph = build_bug_graph()
        assert ("escalate_blocked", "__end__") not in graph.edges, (
            "escalate_blocked must NOT edge directly to END; post_terminal_stats must be between"
        )


class TestBugGraphStatsOrdering:
    """Stats posting occurs AFTER other terminal actions."""

    def test_success_path_order(self):
        """Success path: post_merge_summary → post_terminal_stats → END."""
        graph = build_bug_graph()
        edges = graph.edges
        assert ("post_merge_summary", "post_terminal_stats") in edges, (
            "post_merge_summary must edge to post_terminal_stats"
        )
        assert ("post_terminal_stats", "__end__") in edges, "post_terminal_stats must edge to END"

    def test_blocked_path_order(self):
        """Blocked path: escalate_blocked → post_terminal_stats → END."""
        graph = build_bug_graph()
        edges = graph.edges
        assert ("escalate_blocked", "post_terminal_stats") in edges, (
            "escalate_blocked must edge to post_terminal_stats"
        )
        assert ("post_terminal_stats", "__end__") in edges, "post_terminal_stats must edge to END"

    def test_stats_is_last_before_end(self):
        """post_terminal_stats is the single gateway to END for terminal paths."""
        graph = build_bug_graph()
        # Only post_terminal_stats should have a direct edge to __end__
        # (other terminal nodes go through stats first)
        direct_to_end = {src for (src, dst) in graph.edges if dst == "__end__"}
        # post_terminal_stats must be one such node
        assert "post_terminal_stats" in direct_to_end, (
            "post_terminal_stats must have edge to __end__"
        )
        # Neither escalate_blocked nor post_merge_summary should bypass stats
        assert "escalate_blocked" not in direct_to_end, (
            "escalate_blocked must not directly edge to __end__"
        )
        assert "post_merge_summary" not in direct_to_end, (
            "post_merge_summary must not directly edge to __end__"
        )


class TestBugGraphAllNodesPresent:
    """Bug graph still contains all expected nodes after stats integration."""

    def test_all_core_nodes_still_present(self):
        """Core pipeline nodes are still registered after stats node addition."""
        graph = build_bug_graph()
        compiled = graph.compile()
        expected_nodes = {
            "triage_check",
            "triage_gate",
            "analyze_bug",
            "reflect_rca",
            "rca_option_gate",
            "regenerate_rca",
            "plan_bug_fix",
            "plan_approval_gate",
            "regenerate_plan",
            "decompose_plan",
            "post_merge_summary",
            "post_terminal_stats",
            "escalate_blocked",
        }
        for node in expected_nodes:
            assert node in compiled.nodes, f"Node '{node}' missing from compiled graph"
