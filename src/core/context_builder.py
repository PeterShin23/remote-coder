"""Build context strings for agents based on conversation history."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.models import ConversationInteraction

LOGGER = logging.getLogger(__name__)


class ContextBuilder:
    """Builds formatted context strings for agent task inclusion."""

    @staticmethod
    def build_context_for_agent(
        interactions: list[ConversationInteraction],
        summary: str | None = None,
        summarized_count: int = 0
    ) -> str:
        """
        Build the context section to prepend to agent task.

        If there's a summary and summarized_count > 0, includes the summary
        plus the most recent interactions in detail. Otherwise, shows all
        interactions chronologically.

        Args:
            interactions: List of ConversationInteraction objects
            summary: Optional summary of early interactions
            summarized_count: How many interactions were summarized (0 if no summary)

        Returns:
            Formatted context string ready to include in task_text
        """
        if not interactions:
            return ""

        if summary and summarized_count > 0:
            return ContextBuilder._build_with_summary(
                interactions, summary, summarized_count
            )
        else:
            return ContextBuilder._build_without_summary(interactions)

    @staticmethod
    def _build_without_summary(interactions: list[ConversationInteraction]) -> str:
        """
        Build context when there's no summary (< 10 interactions).

        Shows all interactions chronologically.

        Args:
            interactions: List of interactions to format

        Returns:
            Formatted context string
        """
        lines = []
        for interaction in interactions:
            user_text = interaction.user_message.content
            agent_text = interaction.agent_message.content

            lines.append("USER:")
            lines.append(user_text)
            lines.append("AGENT:")
            lines.append(agent_text)

        return "\n".join(lines)

    @staticmethod
    def _build_with_summary(
        interactions: list[ConversationInteraction],
        summary: str,
        summarized_count: int
    ) -> str:
        """
        Build context when there's a summary.

        Shows summary section, then recent interactions in detail.

        Args:
            interactions: Full list of interactions
            summary: Summary text of early interactions
            summarized_count: How many interactions were summarized

        Returns:
            Formatted context string with summary and recent interactions
        """
        lines = []

        # Add summary section
        lines.append("### SUMMARY BEFORE THESE MESSAGES")
        lines.append(summary)
        lines.append("")
        lines.append("### MORE RECENT MESSAGES")

        # Show interactions after the summarized ones
        for interaction in interactions[summarized_count:]:
            user_text = interaction.user_message.content
            agent_text = interaction.agent_message.content

            lines.append("USER:")
            lines.append(user_text)
            lines.append("AGENT:")
            lines.append(agent_text)

        return "\n".join(lines)

    @staticmethod
    def format_interaction_pair(user_msg: str, agent_msg: str) -> str:
        """
        Format a single interaction pair for context.

        Args:
            user_msg: User message text
            agent_msg: Agent response text

        Returns:
            Formatted interaction pair
        """
        return f"USER:\n{user_msg}\nAGENT:\n{agent_msg}"
