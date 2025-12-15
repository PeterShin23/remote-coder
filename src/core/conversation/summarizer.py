"""Generate summaries of conversation interactions."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.models import ConversationInteraction

LOGGER = logging.getLogger(__name__)


class ConversationSummarizer:
    """Generates concise summaries of conversation interactions."""

    @staticmethod
    def summarize_interactions(
        interactions: list[ConversationInteraction],
        count: int = 5
    ) -> str:
        """
        Summarize first N interactions into a concise summary.

        The summary includes:
        - Key numbers, names, specific requirements mentioned
        - Major decisions made
        - Problems solved
        - Components/features added/modified

        Emphasis is placed on specific details the user mentioned.

        Args:
            interactions: List of ConversationInteraction objects
            count: How many interactions to summarize (default 5)

        Returns:
            A concise summary string of the interactions
        """
        if not interactions:
            return ""

        # Take only the first N interactions
        to_summarize = interactions[:min(count, len(interactions))]

        # Extract key information
        summary_parts = []

        for interaction in to_summarize:
            user_msg = interaction.user_message.content
            agent_msg = interaction.agent_message.content

            # Extract specific details from user message
            user_details = ConversationSummarizer._extract_details(user_msg)

            # Extract what agent accomplished from agent message
            agent_actions = ConversationSummarizer._extract_actions(agent_msg)

            # Combine into summary line if both exist
            if user_details and agent_actions:
                summary_parts.append(
                    f"{user_details}: {agent_actions}"
                )
            elif user_details:
                summary_parts.append(user_details)
            elif agent_actions:
                summary_parts.append(agent_actions)

        # Join parts into a flowing summary
        if not summary_parts:
            return "Conversation about code modifications."

        # Combine parts with period separation, then refine
        raw_summary = ". ".join(summary_parts)
        if not raw_summary.endswith("."):
            raw_summary += "."

        return raw_summary

    @staticmethod
    def _extract_details(text: str) -> str:
        """
        Extract specific details (numbers, names, requirements) from text.

        Args:
            text: The input text to extract from

        Returns:
            A short phrase with key details
        """
        if not text:
            return ""

        # Look for patterns like "52 cards", "2 Jokers", component names, etc.
        # Keep the first sentence or two that contains actionable info
        sentences = re.split(r'[.!?]+', text)
        key_sentence = sentences[0].strip() if sentences else ""

        # Limit to reasonable length
        if len(key_sentence) > 150:
            key_sentence = key_sentence[:150].rsplit(' ', 1)[0] + "..."

        return key_sentence

    @staticmethod
    def _extract_actions(text: str) -> str:
        """
        Extract what the agent actually did from their response.

        Args:
            text: The agent's response text

        Returns:
            A short phrase describing the action taken
        """
        if not text:
            return ""

        # Look for action verbs in agent responses
        action_patterns = [
            r"(added|created|implemented|added).*?(?:[.!?]|$)",
            r"(updated|modified|changed).*?(?:[.!?]|$)",
            r"(fixed|resolved|corrected).*?(?:[.!?]|$)",
            r"(removed|deleted).*?(?:[.!?]|$)",
        ]

        for pattern in action_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                action = match.group(0).strip()
                # Keep it concise
                if len(action) > 120:
                    action = action[:120].rsplit(' ', 1)[0] + "..."
                return action

        # Fallback: first sentence
        sentences = re.split(r'[.!?]+', text)
        first = sentences[0].strip() if sentences else ""

        if len(first) > 120:
            first = first[:120].rsplit(' ', 1)[0] + "..."

        return first
