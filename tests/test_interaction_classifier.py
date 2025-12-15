"""Tests for InteractionClassifier."""

import pytest

from src.agent_adapters.base import AgentResult, FileEdit
from src.core.conversation import InteractionClassifier


class TestInteractionClassifier:
    """Test cases for InteractionClassifier."""

    def test_is_substantive_with_file_edits(self):
        """File edits alone should mark result as substantive."""
        result = AgentResult(
            success=True,
            output_text="Made some changes",
            file_edits=[FileEdit(path="file.py", type="edit")],
        )
        assert InteractionClassifier.is_substantive(result) is True

    def test_is_substantive_with_success_and_text(self):
        """Success with non-empty text should be substantive."""
        result = AgentResult(
            success=True,
            output_text="I added a new function to calculate totals.",
        )
        assert InteractionClassifier.is_substantive(result) is True

    def test_is_substantive_with_text_only(self):
        """Non-empty text alone should be substantive."""
        result = AgentResult(
            success=False,
            output_text="I found an issue with the code.",
        )
        assert InteractionClassifier.is_substantive(result) is True

    def test_is_not_substantive_empty_text_and_no_edits(self):
        """Empty text with no edits should not be substantive."""
        result = AgentResult(
            success=False,
            output_text="",
        )
        assert InteractionClassifier.is_substantive(result) is False

    def test_is_not_substantive_whitespace_only(self):
        """Whitespace-only text should not be substantive."""
        result = AgentResult(
            success=False,
            output_text="   \n  \t  ",
        )
        assert InteractionClassifier.is_substantive(result) is False

    def test_is_substantive_with_file_edits_no_text(self):
        """File edits without text should still be substantive."""
        result = AgentResult(
            success=False,
            output_text="",
            file_edits=[FileEdit(path="test.py", type="create")],
        )
        assert InteractionClassifier.is_substantive(result) is True

    def test_extract_context_content(self):
        """Extract content should return the output_text."""
        result = AgentResult(
            success=True,
            output_text="I implemented the CardList component.",
            file_edits=[FileEdit(path="components.py", type="edit")],
        )
        content = InteractionClassifier.extract_context_content(result)
        assert content == "I implemented the CardList component."

    def test_extract_context_content_empty(self):
        """Extract content should return empty string if output_text is empty."""
        result = AgentResult(
            success=False,
            output_text="",
        )
        content = InteractionClassifier.extract_context_content(result)
        assert content == ""

    def test_is_substantive_success_with_empty_text(self):
        """Success with empty text should not be substantive."""
        result = AgentResult(
            success=True,
            output_text="",
        )
        assert InteractionClassifier.is_substantive(result) is False

    def test_is_substantive_multiple_file_edits(self):
        """Multiple file edits should be substantive."""
        result = AgentResult(
            success=False,
            output_text="Made changes",
            file_edits=[
                FileEdit(path="file1.py", type="edit"),
                FileEdit(path="file2.py", type="create"),
                FileEdit(path="file3.py", type="delete"),
            ],
        )
        assert InteractionClassifier.is_substantive(result) is True
