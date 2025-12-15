"""Tests for ContextBuilder."""

import pytest

from src.core.conversation import ContextBuilder
from src.core.models import ConversationInteraction, ConversationMessage


class TestContextBuilder:
    """Test cases for ContextBuilder."""

    def test_build_context_empty_interactions(self):
        """Building context with no interactions should return empty string."""
        context = ContextBuilder.build_context_for_agent([])
        assert context == ""

    def test_build_context_without_summary_single(self):
        """Build context without summary should show interaction."""
        interaction = ConversationInteraction(
            interaction_number=1,
            user_message=ConversationMessage(role="user", content="Add a CardList"),
            agent_message=ConversationMessage(role="assistant", content="Added CardList component"),
        )

        context = ContextBuilder.build_context_for_agent([interaction])

        assert "USER:" in context
        assert "AGENT:" in context
        assert "Add a CardList" in context
        assert "Added CardList" in context
        assert "SUMMARY" not in context

    def test_build_context_without_summary_multiple(self):
        """Build context without summary should show all interactions."""
        interactions = [
            ConversationInteraction(
                interaction_number=1,
                user_message=ConversationMessage(role="user", content="Request 1"),
                agent_message=ConversationMessage(role="assistant", content="Response 1"),
            ),
            ConversationInteraction(
                interaction_number=2,
                user_message=ConversationMessage(role="user", content="Request 2"),
                agent_message=ConversationMessage(role="assistant", content="Response 2"),
            ),
        ]

        context = ContextBuilder.build_context_for_agent(interactions)

        # Should have all messages
        assert context.count("USER:") == 2
        assert context.count("AGENT:") == 2
        assert "Request 1" in context
        assert "Request 2" in context

    def test_build_context_with_summary(self):
        """Build context with summary should include summary section."""
        interactions = [
            ConversationInteraction(
                interaction_number=i + 1,
                user_message=ConversationMessage(role="user", content=f"Request {i+1}"),
                agent_message=ConversationMessage(role="assistant", content=f"Response {i+1}"),
            )
            for i in range(10)
        ]

        summary = "Built CardList with 52 cards, then added 2 Jokers for total 54."

        context = ContextBuilder.build_context_for_agent(
            interactions,
            summary=summary,
            summarized_count=5
        )

        # Should have summary section
        assert "SUMMARY BEFORE THESE MESSAGES" in context
        assert "MORE RECENT MESSAGES" in context
        assert summary in context

        # Should have recent interactions (6-10)
        assert "Request 6" in context
        assert "Response 6" in context
        assert "Request 10" in context
        assert "Response 10" in context

        # Should NOT have early interactions (1-5) as individual interactions
        # (they're in the summary instead)
        assert "USER:\nRequest 1\nAGENT:\nResponse 1" not in context
        assert "USER:\nRequest 2\nAGENT:\nResponse 2" not in context
        assert context.count("USER:") == 5  # Only requests 6-10

    def test_format_interaction_pair(self):
        """Format a single interaction pair correctly."""
        formatted = ContextBuilder.format_interaction_pair(
            "Add CardList",
            "Added CardList component"
        )

        assert "USER:" in formatted
        assert "AGENT:" in formatted
        assert "Add CardList" in formatted
        assert "Added CardList component" in formatted
        assert formatted.count("\n") >= 2

    def test_build_context_preserves_interaction_order(self):
        """Interactions should be in chronological order."""
        interactions = [
            ConversationInteraction(
                interaction_number=1,
                user_message=ConversationMessage(role="user", content="First"),
                agent_message=ConversationMessage(role="assistant", content="First response"),
            ),
            ConversationInteraction(
                interaction_number=2,
                user_message=ConversationMessage(role="user", content="Second"),
                agent_message=ConversationMessage(role="assistant", content="Second response"),
            ),
        ]

        context = ContextBuilder.build_context_for_agent(interactions)

        # "First" should come before "Second"
        assert context.index("First") < context.index("Second")

    def test_build_context_with_summary_and_many_interactions(self):
        """With summary and 10 interactions, should show summary + recent 5."""
        interactions = [
            ConversationInteraction(
                interaction_number=i + 1,
                user_message=ConversationMessage(role="user", content=f"Request {i+1}"),
                agent_message=ConversationMessage(role="assistant", content=f"Response {i+1}"),
            )
            for i in range(10)
        ]

        summary = "Completed 5 rounds of development work."

        context = ContextBuilder.build_context_for_agent(
            interactions,
            summary=summary,
            summarized_count=5
        )

        # Should have both sections
        assert "SUMMARY" in context
        assert "MORE RECENT" in context

        # Count USER: labels - should be 5 (requests 6-10)
        assert context.count("USER:") == 5

    def test_build_context_without_summary_null_values(self):
        """Build context with None summary should not include summary section."""
        interaction = ConversationInteraction(
            interaction_number=1,
            user_message=ConversationMessage(role="user", content="Test"),
            agent_message=ConversationMessage(role="assistant", content="Response"),
        )

        context = ContextBuilder.build_context_for_agent(
            [interaction],
            summary=None,
            summarized_count=0
        )

        assert "SUMMARY" not in context
        assert "USER:" in context
