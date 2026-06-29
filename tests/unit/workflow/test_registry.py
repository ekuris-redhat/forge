"""Tests for workflow registry."""


from forge.models.workflow import TicketType


class TestDefaultRouter:
    """Tests for create_default_router."""

    def test_creates_router_with_workflows(self):
        """create_default_router returns router with workflows."""
        from forge.workflow.registry import create_default_router

        router = create_default_router()
        workflows = router.list_workflows()

        assert len(workflows) >= 2

    def test_resolves_feature_to_feature_workflow(self):
        """Feature tickets resolve to FeatureWorkflow."""
        from forge.workflow.registry import create_default_router

        router = create_default_router()
        workflow = router.resolve(TicketType.FEATURE, [], {})

        assert workflow is not None
        assert workflow.name == "feature"

    def test_resolves_bug_to_bug_workflow(self):
        """Bug tickets resolve to BugWorkflow."""
        from forge.workflow.registry import create_default_router

        router = create_default_router()
        workflow = router.resolve(TicketType.BUG, [], {})

        assert workflow is not None
        assert workflow.name == "bug"
