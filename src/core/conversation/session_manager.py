"""Manage active sessions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import TYPE_CHECKING, Any, Dict, Sequence, Tuple
from uuid import UUID

from ..errors import SessionNotFound

if TYPE_CHECKING:
    from src.agent_adapters.base import AgentResult
from .classifier import InteractionClassifier
from .summarizer import ConversationSummarizer
from .context_builder import ContextBuilder
from ..models import (
    AgentType,
    ConversationInteraction,
    ConversationMessage,
    Project,
    PullRequestRef,
    Session,
    SessionStatus,
)

LOGGER = logging.getLogger(__name__)


class SessionManager:
    """Thread-safe in-memory session store that tracks history."""

    def __init__(self, history_limit: int = 20) -> None:
        self._sessions: Dict[UUID, Session] = {}
        self._thread_index: Dict[Tuple[str, str], UUID] = {}
        self._pr_refs: Dict[UUID, PullRequestRef] = {}
        self._lock = RLock()
        self._history_limit = history_limit

    def create_session(
        self,
        *,
        project: Project,
        channel_id: str,
        thread_ts: str,
        agent_id: str,
        agent_type: AgentType,
        active_model: str | None = None,
    ) -> Session:
        session = Session(
            project_id=project.id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            active_agent_id=agent_id,
            active_agent_type=agent_type,
            project_path=project.path,
            active_model=active_model,
        )
        with self._lock:
            self._sessions[session.id] = session
            self._thread_index[(channel_id, thread_ts)] = session.id
        LOGGER.info("Session %s created for project %s", session.id, project.id)
        return session

    def get_session(self, session_id: UUID) -> Session:
        with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFound(session_id)
            return self._sessions[session_id]

    def get_by_thread(self, channel_id: str, thread_ts: str) -> Session:
        key = (channel_id, thread_ts)
        with self._lock:
            session_id = self._thread_index.get(key)
            if not session_id:
                raise SessionNotFound("unknown-thread")
        return self.get_session(session_id)

    def set_active_agent(
        self,
        session_id: UUID,
        agent_id: str,
        agent_type: AgentType,
        model: str | None = None,
    ) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise SessionNotFound(session_id)
            session.active_agent_id = agent_id
            session.active_agent_type = agent_type
            if model is not None:
                session.active_model = model
            session.updated_at = datetime.now(timezone.utc)

    def append_user_message(self, session_id: UUID, text: str) -> None:
        self._append_message(session_id, role="user", content=text)

    def append_agent_message(self, session_id: UUID, text: str) -> None:
        self._append_message(session_id, role="assistant", content=text)

    def _append_message(self, session_id: UUID, role: str, content: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise SessionNotFound(session_id)
            session.conversation_history.append(ConversationMessage(role=role, content=content))
            if len(session.conversation_history) > self._history_limit:
                session.conversation_history = session.conversation_history[-self._history_limit :]
            session.updated_at = datetime.now(timezone.utc)

    def get_conversation_history(self, session_id: UUID) -> list[ConversationMessage]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise SessionNotFound(session_id)
            return list(session.conversation_history)

    def update_session_context(self, session_id: UUID, context_delta: Dict) -> None:
        if not context_delta:
            return
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise SessionNotFound(session_id)
            session.session_context.update(context_delta)
            session.updated_at = datetime.now(timezone.utc)

    def update_status(self, session_id: UUID, status: SessionStatus) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise SessionNotFound(session_id)
            session.status = status
            session.updated_at = datetime.now(timezone.utc)

    def list_active(self) -> list[Session]:
        with self._lock:
            return [s for s in self._sessions.values() if s.status == SessionStatus.ACTIVE]

    def cleanup_ended(self, older_than: timedelta) -> int:
        cutoff = datetime.now(timezone.utc) - older_than
        with self._lock:
            to_remove = [sid for sid, session in self._sessions.items() if session.updated_at < cutoff]
            for sid in to_remove:
                self._sessions.pop(sid, None)
                self._pr_refs.pop(sid, None)
            self._thread_index = {k: v for k, v in self._thread_index.items() if v not in to_remove}
        return len(to_remove)

    def clear_all(self) -> int:
        """Remove all sessions and associated references."""
        with self._lock:
            count = len(self._sessions)
            self._sessions.clear()
            self._thread_index.clear()
            self._pr_refs.clear()
        return count

    def append_interaction(
        self,
        session_id: UUID,
        user_message: ConversationMessage,
        agent_result: AgentResult,
        classifier: InteractionClassifier,
    ) -> None:
        """
        Create and append an interaction if agent result is substantive.
        Automatically manage summarization when hitting 10 interactions.

        Args:
            session_id: The session UUID
            user_message: The user's request (ConversationMessage)
            agent_result: The structured result from agent adapter (AgentResult)
            classifier: InteractionClassifier instance
        """
        # Check if result is substantive
        if not classifier.is_substantive(agent_result):
            LOGGER.debug("Agent result is not substantive, skipping interaction")
            return

        # Extract the content
        agent_text = classifier.extract_context_content(agent_result)
        agent_message = ConversationMessage(role="assistant", content=agent_text)

        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise SessionNotFound(session_id)

            # Create interaction with 1-indexed number
            interaction_number = len(session.interactions) + 1
            interaction = ConversationInteraction(
                interaction_number=interaction_number,
                user_message=user_message,
                agent_message=agent_message,
            )

            session.interactions.append(interaction)
            session.updated_at = datetime.now(timezone.utc)

            LOGGER.info(
                "Appended interaction #%d to session %s",
                interaction_number,
                session_id
            )

            # Check if we should trigger summarization
            if len(session.interactions) == 10:
                LOGGER.info(
                    "Session %s reached 10 interactions, triggering summarization",
                    session_id
                )
                self._perform_summarization_locked(session)

    def _perform_summarization_locked(self, session: Session) -> None:
        """
        Perform summarization on a session (assumes lock is held).

        Summarizes interactions 1-5, marks them as summarized,
        keeps interactions 6-10 in detail.

        Args:
            session: The session to summarize
        """
        if session.conversation_summary is not None:
            # Already summarized
            LOGGER.debug("Session already has a summary, skipping")
            return

        # Summarize first 5 interactions
        interactions_to_summarize = session.interactions[:5]
        summary = ConversationSummarizer.summarize_interactions(
            interactions_to_summarize,
            count=5
        )

        # Mark these interactions as summarized
        for interaction in interactions_to_summarize:
            interaction.is_summarized = True

        # Store summary in session
        session.conversation_summary = summary
        session.summary_interaction_count = 5

        LOGGER.info("Summarized first 5 interactions for session %s", session.id)

    def should_summarize(self, session_id: UUID) -> bool:
        """
        Check if a session should have summarization performed.

        Returns True if the session just reached 10 interactions
        and doesn't have a summary yet.

        Args:
            session_id: The session UUID

        Returns:
            True if summarization should be performed
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False

            # Summarize if we have exactly 10 interactions and no summary yet
            return (
                len(session.interactions) == 10
                and session.conversation_summary is None
            )

    def perform_summarization(self, session_id: UUID) -> None:
        """
        Perform summarization on a session.

        Summarizes interactions 1-5, marks them as summarized,
        keeps interactions 6-10 in detail.

        Args:
            session_id: The session UUID
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise SessionNotFound(session_id)
            self._perform_summarization_locked(session)

    def get_context_for_agent(self, session_id: UUID) -> str:
        """
        Get formatted context string ready to prepend to task_text.

        Includes full history or summary + recent interactions based on
        the current state of the conversation.

        Args:
            session_id: The session UUID

        Returns:
            Formatted context string (may be empty if no interactions)
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise SessionNotFound(session_id)

            # Build context using ContextBuilder
            context = ContextBuilder.build_context_for_agent(
                interactions=session.interactions,
                summary=session.conversation_summary,
                summarized_count=session.summary_interaction_count,
            )

            return context

    def set_pr_ref(self, pr_ref: PullRequestRef) -> None:
        with self._lock:
            self._pr_refs[pr_ref.session_id] = pr_ref

    def get_pr_ref(self, session_id: UUID) -> PullRequestRef:
        with self._lock:
            if session_id not in self._pr_refs:
                raise SessionNotFound(session_id)
            return self._pr_refs[session_id]
