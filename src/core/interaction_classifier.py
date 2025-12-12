"""Classify agent responses to determine what goes into conversation history."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.agent_adapters.base import AgentResult

LOGGER = logging.getLogger(__name__)


class InteractionClassifier:
    """Classifies agent results to determine substantive work."""

    @staticmethod
    def is_substantive(result: AgentResult) -> bool:
        """
        Returns True if the agent result represents substantive work.

        A result is substantive if:
        1. Agent made file edits (len(result.file_edits) > 0), OR
        2. Agent reported success (result.success == True), OR
        3. Agent returned meaningful text content (not empty/whitespace)

        Uses structured output fields rather than pattern matching on text.
        This avoids brittleness when agents change their messaging.

        Args:
            result: The AgentResult from an agent adapter

        Returns:
            True if the result should be included in conversation history
        """
        # File edits are definitive proof of work
        if result.file_edits:
            return True

        # Success flag indicates meaningful work was done
        if result.success and result.output_text.strip():
            return True

        # Any meaningful text content counts as substantive
        # (even if not explicitly marked as success)
        if result.output_text.strip():
            return True

        return False

    @staticmethod
    def extract_context_content(result: AgentResult) -> str:
        """
        Extract the main content for conversation history.

        Returns the substantive text from result.output_text, which is
        the agent's description of what was done.

        Args:
            result: The AgentResult from an agent adapter

        Returns:
            The output text to include in conversation history
        """
        return result.output_text
