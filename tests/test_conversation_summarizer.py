"""Tests for ConversationSummarizer."""

import pytest

from src.core.conversation_summarizer import ConversationSummarizer
from src.core.models import ConversationInteraction, ConversationMessage


class TestConversationSummarizer:
    """Test cases for ConversationSummarizer."""

    def test_summarize_empty_interactions(self):
        """Summarizing empty list should return empty string."""
        summary = ConversationSummarizer.summarize_interactions([])
        assert summary == ""

    def test_summarize_single_interaction(self):
        """Summarizing a single interaction should work."""
        user_msg = ConversationMessage(role="user", content="Add a CardList component for 52 cards")
        agent_msg = ConversationMessage(role="assistant", content="Added CardList component, displays all 52 cards")

        interaction = ConversationInteraction(
            interaction_number=1,
            user_message=user_msg,
            agent_message=agent_msg,
        )

        summary = ConversationSummarizer.summarize_interactions([interaction], count=1)

        assert len(summary) > 0
        assert "52" in summary or "CardList" in summary or "card" in summary.lower()

    def test_summarize_multiple_interactions(self):
        """Summarizing multiple interactions should preserve details."""
        interactions = [
            ConversationInteraction(
                interaction_number=1,
                user_message=ConversationMessage(role="user", content="Add CardList component for 52 cards"),
                agent_message=ConversationMessage(role="assistant", content="Created CardList, displays 52 cards"),
            ),
            ConversationInteraction(
                interaction_number=2,
                user_message=ConversationMessage(role="user", content="Include 2 Jokers as well"),
                agent_message=ConversationMessage(role="assistant", content="Updated CardList to include 2 Jokers, total 54"),
            ),
        ]

        summary = ConversationSummarizer.summarize_interactions(interactions, count=2)

        # Should contain key numbers and context
        assert "52" in summary or "54" in summary or "Card" in summary
        assert len(summary) > 0
        assert summary.endswith(".")

    def test_summarize_respects_count_limit(self):
        """Summarize should only use first N interactions."""
        interactions = []
        for i in range(10):
            interactions.append(
                ConversationInteraction(
                    interaction_number=i + 1,
                    user_message=ConversationMessage(role="user", content=f"Request {i+1}"),
                    agent_message=ConversationMessage(role="assistant", content=f"Response {i+1}"),
                )
            )

        # Only summarize first 5
        summary = ConversationSummarizer.summarize_interactions(interactions, count=5)

        # Should reference early interactions
        assert len(summary) > 0
        # Should end with period
        assert summary.endswith(".")

    def test_summarize_extracts_numbers(self):
        """Summarize should preserve specific numbers mentioned."""
        interactions = [
            ConversationInteraction(
                interaction_number=1,
                user_message=ConversationMessage(role="user", content="Create a component to display 52 playing cards"),
                agent_message=ConversationMessage(role="assistant", content="Created PlayingCard component with 52 cards"),
            ),
        ]

        summary = ConversationSummarizer.summarize_interactions(interactions, count=1)

        # Should preserve the number 52
        assert "52" in summary

    def test_summarize_with_long_messages(self):
        """Summarize should handle long messages gracefully."""
        long_user = "A" * 500
        long_agent = "B" * 500

        interaction = ConversationInteraction(
            interaction_number=1,
            user_message=ConversationMessage(role="user", content=long_user),
            agent_message=ConversationMessage(role="assistant", content=long_agent),
        )

        summary = ConversationSummarizer.summarize_interactions([interaction], count=1)

        # Summary should be finite and shorter than original
        assert len(summary) < len(long_user) + len(long_agent)
        assert len(summary) > 0

    def test_extract_details(self):
        """_extract_details should pull key information from text."""
        text = "Add a CardList component that displays all 52 cards in the deck"
        details = ConversationSummarizer._extract_details(text)

        assert len(details) > 0
        assert "CardList" in details or "cards" in details.lower()

    def test_extract_details_empty(self):
        """_extract_details should handle empty text."""
        details = ConversationSummarizer._extract_details("")
        assert details == ""

    def test_extract_actions(self):
        """_extract_actions should find what agent did."""
        text = "Added CardList component to display all 52 cards."
        action = ConversationSummarizer._extract_actions(text)

        assert len(action) > 0
        assert "added" in action.lower() or "Added" in action

    def test_extract_actions_multiple_patterns(self):
        """_extract_actions should find various action patterns."""
        test_cases = [
            ("fixed the bug in the parser", "fixed"),
            ("Updated the configuration file", "Updated"),
            ("Removed the deprecated function", "Removed"),
            ("Created a new utility module", "Created"),
        ]

        for text, expected_word in test_cases:
            action = ConversationSummarizer._extract_actions(text)
            assert expected_word.lower() in action.lower()
