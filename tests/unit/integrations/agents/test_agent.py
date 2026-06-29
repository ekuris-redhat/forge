"""Unit tests for ForgeAgent."""

from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from forge.integrations.agents.agent import ForgeAgent


@pytest.mark.asyncio
async def test_answer_question():
    """ForgeAgent can answer questions about artifacts."""
    agent = ForgeAgent()

    with patch.object(agent, "run_task", new_callable=AsyncMock) as mock_run_task:
        mock_run_task.return_value = "Because of performance"

        answer = await agent.answer_question(
            question="Why REST?",
            artifact_content="# PRD\n\nWe use REST",
            context={
                "artifact_type": "prd",
                "generation_context": {"raw_requirements": "Build API"},
            },
        )

    assert "performance" in answer
    mock_run_task.assert_called_once()
    call_kwargs = mock_run_task.call_args
    assert call_kwargs.kwargs["task"] == "answer-question"

    await agent.close()


@pytest.mark.asyncio
async def test_answer_question_default_artifact_type():
    """ForgeAgent uses default artifact type when not provided."""
    agent = ForgeAgent()

    with patch.object(agent, "run_task", new_callable=AsyncMock) as mock_run_task:
        mock_run_task.return_value = "The answer"

        await agent.answer_question(
            question="What is this?",
            artifact_content="Some content",
            context={},  # No artifact_type provided
        )

    call_kwargs = mock_run_task.call_args
    # The prompt should use "document" as default artifact type
    assert call_kwargs.kwargs["context"]["artifact_type"] == "document"

    await agent.close()


@pytest.mark.asyncio
async def test_answer_question_empty_response():
    """ForgeAgent handles empty response gracefully."""
    agent = ForgeAgent()

    with patch.object(agent, "run_task", new_callable=AsyncMock) as mock_run_task:
        mock_run_task.return_value = ""

        answer = await agent.answer_question(
            question="Test?",
            artifact_content="Content",
            context={"artifact_type": "spec"},
        )

    assert answer == ""

    await agent.close()


def test_get_skill_paths_uses_resolver_when_ticket_key_given():
    """When ticket_key is provided, resolver is called and result returned."""
    agent = ForgeAgent.__new__(ForgeAgent)
    agent.settings = MagicMock()

    with patch("forge.integrations.agents.agent.resolve_skill_paths") as mock_resolver:
        mock_resolver.return_value = ["skills/default/", "skills/proj/"]
        result = agent._get_skill_paths("PROJ-123")

    mock_resolver.assert_called_once()
    assert result == ["skills/default/", "skills/proj/"]


def test_get_skill_paths_returns_default_without_ticket_key():
    """When ticket_key is None, resolver returns skills/default/ only."""
    agent = ForgeAgent.__new__(ForgeAgent)
    agent.settings = MagicMock()
    agent.settings.skills_dir = "skills/"

    with patch("forge.integrations.agents.agent.resolve_skill_paths") as mock_resolver:
        mock_resolver.return_value = ["skills/default/"]
        result = agent._get_skill_paths(None)

    mock_resolver.assert_called_once_with("", ANY)
    assert result == ["skills/default/"]


@pytest.mark.asyncio
async def test_run_agent_token_aggregation():
    """_run_agent aggregates token counts from AIMessage usage_metadata."""
    agent = ForgeAgent()

    class AIMessage:
        def __init__(self, content, usage_metadata):
            self.content = content
            self.usage_metadata = usage_metadata

    msg1 = AIMessage("Hello", {"input_tokens": 10, "output_tokens": 5})
    msg2 = AIMessage("World", {"input_tokens": 20, "output_tokens": 15})

    mock_agent = AsyncMock()
    mock_agent.ainvoke.return_value = {"messages": [msg1, msg2]}

    with patch.object(agent, "_create_agent_async", return_value=mock_agent):
        text, in_tokens, out_tokens = await agent._run_agent(
            prompt="test prompt",
            system_prompt="system prompt",
        )

    assert text == "Hello\nWorld"
    assert in_tokens == 30
    assert out_tokens == 20

    await agent.close()


@pytest.mark.asyncio
async def test_run_task_populates_last_tokens():
    """run_task updates the last_input_tokens and last_output_tokens attributes on ForgeAgent."""
    agent = ForgeAgent()

    with patch.object(agent, "_run_agent", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = ("Final response", 123, 456)
        with patch("forge.integrations.agents.agent.load_prompt", return_value="system prompt"):
            res = await agent.run_task(task="test-task", prompt="input prompt")

    assert res == "Final response"
    assert agent.last_input_tokens == 123
    assert agent.last_output_tokens == 456

    await agent.close()
