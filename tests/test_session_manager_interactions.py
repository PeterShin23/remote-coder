"""Integration tests for SessionManager interaction tracking."""

import pytest

from src.agent_adapters.base import AgentResult, FileEdit
from src.core.conversation import InteractionClassifier, SessionManager
from src.core.models import (
    Agent,
    AgentType,
    ConversationMessage,
    Project,
    WorkingDirMode,
)
from pathlib import Path


class TestSessionManagerInteractions:
    """Test cases for SessionManager interaction tracking."""

    @pytest.fixture
    def session_manager(self):
        """Create a SessionManager instance for testing."""
        return SessionManager(history_limit=20)

    @pytest.fixture
    def classifier(self):
        """Create an InteractionClassifier instance."""
        return InteractionClassifier()

    @pytest.fixture
    def test_project(self, tmp_path):
        """Create a test project."""
        return Project(
            id="test-project",
            channel_name="test-channel",
            path=tmp_path,
            default_agent_id="claude",
        )

    def test_append_interaction_substantive(self, session_manager, classifier, test_project):
        """Appending a substantive interaction should add it."""
        session = session_manager.create_session(
            project=test_project,
            channel_id="C123",
            thread_ts="1234567890.123456",
            agent_id="claude",
            agent_type=AgentType.CLAUDE,
        )

        user_msg = ConversationMessage(role="user", content="Add a component")
        agent_result = AgentResult(
            success=True,
            output_text="Added component to the project",
            file_edits=[FileEdit(path="component.py", type="create")],
        )

        session_manager.append_interaction(
            session.id,
            user_message=user_msg,
            agent_result=agent_result,
            classifier=classifier,
        )

        # Verify interaction was added
        assert len(session.interactions) == 1
        assert session.interactions[0].user_message.content == "Add a component"
        assert session.interactions[0].agent_message.content == "Added component to the project"

    def test_append_interaction_non_substantive(self, session_manager, classifier, test_project):
        """Appending a non-substantive interaction should skip it."""
        session = session_manager.create_session(
            project=test_project,
            channel_id="C123",
            thread_ts="1234567890.123456",
            agent_id="claude",
            agent_type=AgentType.CLAUDE,
        )

        user_msg = ConversationMessage(role="user", content="What's the status?")
        agent_result = AgentResult(
            success=False,
            output_text="",  # Empty text, not substantive
        )

        session_manager.append_interaction(
            session.id,
            user_message=user_msg,
            agent_result=agent_result,
            classifier=classifier,
        )

        # Should NOT add non-substantive interaction
        assert len(session.interactions) == 0

    def test_append_multiple_interactions(self, session_manager, classifier, test_project):
        """Should track multiple interactions correctly."""
        session = session_manager.create_session(
            project=test_project,
            channel_id="C123",
            thread_ts="1234567890.123456",
            agent_id="claude",
            agent_type=AgentType.CLAUDE,
        )

        for i in range(5):
            user_msg = ConversationMessage(role="user", content=f"Request {i+1}")
            agent_result = AgentResult(
                success=True,
                output_text=f"Completed request {i+1}",
            )

            session_manager.append_interaction(
                session.id,
                user_message=user_msg,
                agent_result=agent_result,
                classifier=classifier,
            )

        assert len(session.interactions) == 5
        # Check interaction numbers are 1-indexed
        for i, interaction in enumerate(session.interactions):
            assert interaction.interaction_number == i + 1

    def test_summarization_at_10_interactions(self, session_manager, classifier, test_project):
        """Summarization should trigger automatically at 10 interactions."""
        session = session_manager.create_session(
            project=test_project,
            channel_id="C123",
            thread_ts="1234567890.123456",
            agent_id="claude",
            agent_type=AgentType.CLAUDE,
        )

        # Add 10 interactions
        for i in range(10):
            user_msg = ConversationMessage(role="user", content=f"Request {i+1}")
            agent_result = AgentResult(
                success=True,
                output_text=f"Completed request {i+1}",
            )

            session_manager.append_interaction(
                session.id,
                user_message=user_msg,
                agent_result=agent_result,
                classifier=classifier,
            )

        # After 10 interactions, summarization should have occurred
        assert session.conversation_summary is not None
        assert session.summary_interaction_count == 5

        # First 5 should be marked as summarized
        for i in range(5):
            assert session.interactions[i].is_summarized is True

        # Last 5 should not be summarized
        for i in range(5, 10):
            assert session.interactions[i].is_summarized is False

    def test_get_context_for_agent_no_interactions(self, session_manager, test_project):
        """Context with no interactions should be empty."""
        session = session_manager.create_session(
            project=test_project,
            channel_id="C123",
            thread_ts="1234567890.123456",
            agent_id="claude",
            agent_type=AgentType.CLAUDE,
        )

        context = session_manager.get_context_for_agent(session.id)
        assert context == ""

    def test_get_context_for_agent_with_interactions(self, session_manager, classifier, test_project):
        """Context should include interactions."""
        session = session_manager.create_session(
            project=test_project,
            channel_id="C123",
            thread_ts="1234567890.123456",
            agent_id="claude",
            agent_type=AgentType.CLAUDE,
        )

        user_msg = ConversationMessage(role="user", content="Add CardList for 52 cards")
        agent_result = AgentResult(
            success=True,
            output_text="Added CardList component with 52 cards",
        )

        session_manager.append_interaction(
            session.id,
            user_message=user_msg,
            agent_result=agent_result,
            classifier=classifier,
        )

        context = session_manager.get_context_for_agent(session.id)

        assert "USER:" in context
        assert "AGENT:" in context
        assert "52 cards" in context

    def test_get_context_for_agent_with_summary(self, session_manager, classifier, test_project):
        """Context should include summary after 10 interactions."""
        session = session_manager.create_session(
            project=test_project,
            channel_id="C123",
            thread_ts="1234567890.123456",
            agent_id="claude",
            agent_type=AgentType.CLAUDE,
        )

        # Add 10 interactions to trigger summarization
        for i in range(10):
            user_msg = ConversationMessage(role="user", content=f"Request {i+1}")
            agent_result = AgentResult(
                success=True,
                output_text=f"Completed {i+1}",
            )

            session_manager.append_interaction(
                session.id,
                user_message=user_msg,
                agent_result=agent_result,
                classifier=classifier,
            )

        context = session_manager.get_context_for_agent(session.id)

        # Should include summary markers
        assert "SUMMARY BEFORE THESE MESSAGES" in context
        assert "MORE RECENT MESSAGES" in context

    def test_should_summarize_at_exactly_10(self, session_manager, classifier, test_project):
        """should_summarize should return True at exactly 10 interactions."""
        session = session_manager.create_session(
            project=test_project,
            channel_id="C123",
            thread_ts="1234567890.123456",
            agent_id="claude",
            agent_type=AgentType.CLAUDE,
        )

        # Add 9 interactions - should not summarize yet
        for i in range(9):
            user_msg = ConversationMessage(role="user", content=f"Request {i+1}")
            agent_result = AgentResult(
                success=True,
                output_text=f"Completed {i+1}",
            )

            session_manager.append_interaction(
                session.id,
                user_message=user_msg,
                agent_result=agent_result,
                classifier=classifier,
            )

        assert session_manager.should_summarize(session.id) is False

        # Add 10th interaction - now it should have summarized
        user_msg = ConversationMessage(role="user", content="Request 10")
        agent_result = AgentResult(
            success=True,
            output_text="Completed 10",
        )

        session_manager.append_interaction(
            session.id,
            user_message=user_msg,
            agent_result=agent_result,
            classifier=classifier,
        )

        # The append_interaction already triggered summarization internally
        assert session.conversation_summary is not None

    def test_interaction_numbers_are_1_indexed(self, session_manager, classifier, test_project):
        """Interaction numbers should be 1-indexed."""
        session = session_manager.create_session(
            project=test_project,
            channel_id="C123",
            thread_ts="1234567890.123456",
            agent_id="claude",
            agent_type=AgentType.CLAUDE,
        )

        for i in range(3):
            user_msg = ConversationMessage(role="user", content=f"Request {i+1}")
            agent_result = AgentResult(
                success=True,
                output_text=f"Response {i+1}",
            )

            session_manager.append_interaction(
                session.id,
                user_message=user_msg,
                agent_result=agent_result,
                classifier=classifier,
            )

        assert session.interactions[0].interaction_number == 1
        assert session.interactions[1].interaction_number == 2
        assert session.interactions[2].interaction_number == 3

    def test_only_substantive_counted_for_summarization(self, session_manager, classifier, test_project):
        """Only substantive interactions should count toward summarization trigger."""
        session = session_manager.create_session(
            project=test_project,
            channel_id="C123",
            thread_ts="1234567890.123456",
            agent_id="claude",
            agent_type=AgentType.CLAUDE,
        )

        # Add 10 substantive interactions
        for i in range(10):
            user_msg = ConversationMessage(role="user", content=f"Request {i+1}")
            agent_result = AgentResult(
                success=True,
                output_text=f"Response {i+1}",
            )

            session_manager.append_interaction(
                session.id,
                user_message=user_msg,
                agent_result=agent_result,
                classifier=classifier,
            )

        # Try to add a non-substantive interaction
        user_msg = ConversationMessage(role="user", content="Status check")
        agent_result = AgentResult(
            success=False,
            output_text="",
        )

        session_manager.append_interaction(
            session.id,
            user_message=user_msg,
            agent_result=agent_result,
            classifier=classifier,
        )

        # Should still have exactly 10 substantive interactions
        assert len(session.interactions) == 10
        # Summary should have been triggered
        assert session.conversation_summary is not None
