"""Manage active sessions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Dict, Tuple
from uuid import UUID

from .errors import SessionNotFound
from .models import (
    AgentType,
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
    ) -> Session:
        session = Session(
            project_id=project.id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            active_agent_id=agent_id,
            active_agent_type=agent_type,
            project_path=project.path,
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

    def set_active_agent(self, session_id: UUID, agent_id: str, agent_type: AgentType) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise SessionNotFound(session_id)
            session.active_agent_id = agent_id
            session.active_agent_type = agent_type
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

    def set_pr_ref(self, pr_ref: PullRequestRef) -> None:
        with self._lock:
            self._pr_refs[pr_ref.session_id] = pr_ref

    def get_pr_ref(self, session_id: UUID) -> PullRequestRef:
        with self._lock:
            if session_id not in self._pr_refs:
                raise SessionNotFound(session_id)
            return self._pr_refs[session_id]
