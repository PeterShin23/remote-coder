"""Manage active Cockpit sessions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Dict, Tuple
from uuid import UUID

from .errors import SessionNotFound
from .models import PullRequestRef, Session, SessionStatus

LOGGER = logging.getLogger(__name__)


class SessionManager:
    """Thread-safe in-memory session store."""

    def __init__(self) -> None:
        self._sessions: Dict[UUID, Session] = {}
        self._thread_index: Dict[Tuple[str, str], UUID] = {}
        self._pr_refs: Dict[UUID, PullRequestRef] = {}
        self._lock = RLock()

    def create_session(
        self, project_id: str, channel: str, thread_ts: str, agent_id: str
    ) -> Session:
        session = Session(
            project_id=project_id,
            slack_channel=channel,
            slack_thread_ts=thread_ts,
            active_agent_id=agent_id,
        )
        with self._lock:
            self._sessions[session.id] = session
            self._thread_index[(channel, thread_ts)] = session.id
        LOGGER.info("Session %s created for project %s", session.id, project_id)
        return session

    def get_session(self, session_id: UUID) -> Session:
        with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFound(session_id)
            return self._sessions[session_id]

    def get_by_thread(self, channel: str, thread_ts: str) -> Session:
        key = (channel, thread_ts)
        with self._lock:
            session_id = self._thread_index.get(key)
            if not session_id:
                raise SessionNotFound("unknown-thread")
        return self.get_session(session_id)

    def update_active_agent(self, session_id: UUID, agent_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise SessionNotFound(session_id)
            session.active_agent_id = agent_id
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
