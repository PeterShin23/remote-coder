"""Routes Slack events to core logic."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, Sequence

from ..agent_adapters import AgentAdapter, ClaudeAdapter, CodexAdapter
from ..chat_adapters.i_chat_adapter import IChatAdapter
from .command_parser import MENTION_PREFIX, ParsedCommand, parse_command
from .config import Config
from .errors import AgentNotFound, ProjectNotFound, SessionNotFound
from .models import Agent, AgentType, Project, Session, SessionStatus
from .session_manager import SessionManager

LOGGER = logging.getLogger(__name__)


class Router:
    """Central orchestrator translating Slack messages into agent executions."""

    def __init__(
        self,
        session_manager: SessionManager,
        config: Config,
    ) -> None:
        self._session_manager = session_manager
        self._config = config
        self._chat_adapter: Optional[IChatAdapter] = None
        self._adapter_cache: Dict[str, AgentAdapter] = {}
        self._session_locks: Dict[str, asyncio.Lock] = {}

    def bind_adapter(self, adapter: IChatAdapter) -> None:
        """Attach the chat adapter so the router can send replies."""

        self._chat_adapter = adapter

    async def handle_message(self, event: Dict[str, Any]) -> None:
        channel_id = event.get("channel")
        channel_lookup = event.get("channel_name") or channel_id
        text = (event.get("text") or "").strip()
        thread_ts = event.get("thread_ts") or event.get("ts")

        if not channel_id or not thread_ts:
            LOGGER.debug("Ignoring Slack event missing channel or thread")
            return

        try:
            project = self._config.get_project_by_channel(channel_lookup)
        except ProjectNotFound:
            LOGGER.warning("No project mapping for channel %s", channel_lookup)
            return

        session, created = self._get_or_create_session(project, channel_id, thread_ts)

        command = parse_command(text) or self._parse_bot_command(text)
        if command:
            await self._handle_command(command, session, channel_id, thread_ts)
            return

        if not text:
            LOGGER.debug("Ignoring empty Slack message in %s", channel_lookup)
            return

        if session.status == SessionStatus.ENDED:
            await self._send_message(
                channel_id,
                thread_ts,
                "This session has ended. Start a new Slack thread to begin another run.",
            )
            return

        lock = self._get_session_lock(str(session.id))
        async with lock:
            await self._run_agent_interaction(session, project, channel_id, thread_ts, text, created)

    def _get_or_create_session(self, project: Project, channel_id: str, thread_ts: str) -> tuple[Session, bool]:
        try:
            return self._session_manager.get_by_thread(channel_id, thread_ts), False
        except SessionNotFound:
            default_agent = self._config.get_agent(project.default_agent_id)
            session = self._session_manager.create_session(
                project=project,
                channel_id=channel_id,
                thread_ts=thread_ts,
                agent_id=default_agent.id,
                agent_type=default_agent.type,
            )
            return session, True

    async def _run_agent_interaction(
        self,
        session: Session,
        project: Project,
        channel_id: str,
        thread_ts: str,
        user_text: str,
        session_created: bool,
    ) -> None:
        if session_created:
            await self._send_message(
                channel_id,
                thread_ts,
                f"Starting session for `{project.id}` with `{session.active_agent_id}`. "
                "Send a message with your request.",
            )

        agent = self._config.get_agent(session.active_agent_id)
        adapter = self._get_adapter(agent)

        history_snapshot = self._session_manager.get_conversation_history(session.id)
        adapter_history = self._format_history_for_adapter(history_snapshot)
        task_text = self._build_task_text(history_snapshot, user_text)

        self._session_manager.append_user_message(session.id, user_text)

        try:
                result = await adapter.run(
                    task_text=task_text,
                    project_path=str(session.project_path),
                    session_id=str(session.id),
                conversation_history=adapter_history,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            LOGGER.exception("Adapter %s failed", agent.id)
            await self._send_message(
                channel_id,
                thread_ts,
                f"Failed to run `{agent.id}`: {exc}",
            )
            return

        response_text = result.output_text or "Agent completed with no textual output."
        if result.errors:
            response_text = f"{response_text}\n\nErrors:\n" + "\n".join(result.errors)
        if result.file_edits:
            edits_summary = ", ".join({edit.path for edit in result.file_edits})
            response_text = f"{response_text}\n\nDetected file edits: {edits_summary}"

        self._session_manager.append_agent_message(session.id, response_text)
        self._session_manager.update_session_context(session.id, result.session_context)

        await self._send_message(channel_id, thread_ts, response_text)

    def _parse_bot_command(self, text: str) -> Optional[ParsedCommand]:
        normalized = text.strip()
        normalized = MENTION_PREFIX.sub("", normalized, count=1)
        if normalized.lower().startswith("@remote-coder"):
            normalized = normalized[len("@remote-coder") :].strip()
        if normalized.lower().startswith("remote-coder"):
            normalized = normalized[len("remote-coder") :].strip()
        if not normalized:
            return None
        parts = normalized.split()
        if not parts:
            return None
        name = parts[0].lower()
        if name in {"use", "status", "end"}:
            return ParsedCommand(name=name, args=parts[1:])
        return None

    async def _handle_command(
        self,
        command: ParsedCommand,
        session: Session,
        channel_id: str,
        thread_ts: str,
    ) -> None:
        if command.name in {"switch", "use"}:
            await self._command_switch_agent(command, session, channel_id, thread_ts)
        elif command.name == "end":
            await self._command_end_session(session, channel_id, thread_ts)
        elif command.name == "status":
            await self._command_status(session, channel_id, thread_ts)
        else:
            await self._send_message(channel_id, thread_ts, f"Unknown command `{command.name}`")

    async def _command_switch_agent(
        self,
        command: ParsedCommand,
        session: Session,
        channel: str,
        thread_ts: str,
    ) -> None:
        if not command.args:
            await self._send_message(channel, thread_ts, "Usage: use <agent-id>")
            return

        agent_id = command.args[0]
        try:
            agent = self._config.get_agent(agent_id)
        except AgentNotFound:
            await self._send_message(channel, thread_ts, f"Unknown agent `{agent_id}`")
            return

        self._session_manager.set_active_agent(session.id, agent_id, agent.type)
        await self._send_message(channel, thread_ts, f"Switched to `{agent_id}`")

    async def _command_end_session(self, session: Session, channel: str, thread_ts: str) -> None:
        if session.status == SessionStatus.ENDED:
            await self._send_message(channel, thread_ts, "Session already ended.")
            return
        self._session_manager.update_status(session.id, SessionStatus.ENDED)
        await self._send_message(channel, thread_ts, "Session ended. Start a new thread to begin again.")

    async def _command_status(self, session: Session, channel: str, thread_ts: str) -> None:
        history = self._session_manager.get_conversation_history(session.id)
        status_lines = [
            f"Session ID: `{session.id}`",
            f"Project: `{session.project_id}`",
            f"Active agent: `{session.active_agent_id}` ({session.active_agent_type.value})",
            f"Messages stored: {len(history)}",
            f"Status: {session.status.value}",
        ]
        await self._send_message(channel, thread_ts, "\n".join(status_lines))

    def _build_task_text(self, history: Sequence, user_text: str) -> str:
        if not history:
            return user_text
        recent = history[-5:]
        formatted = "\n".join(
            f"{'User' if msg.role == 'user' else 'Assistant'}: {msg.content}".strip()
            for msg in recent
            if msg.content
        )
        return f"Recent context:\n{formatted}\n\nCurrent request:\n{user_text}"

    def _format_history_for_adapter(self, history: Sequence) -> list[Dict[str, str]]:
        formatted: list[Dict[str, str]] = []
        for msg in history:
            formatted.append(
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                }
            )
        return formatted

    def _get_adapter(self, agent: Agent) -> AgentAdapter:
        cached = self._adapter_cache.get(agent.id)
        if cached:
            return cached

        adapter = self._build_adapter(agent)
        self._adapter_cache[agent.id] = adapter
        return adapter

    def _build_adapter(self, agent: Agent) -> AgentAdapter:
        if agent.type == AgentType.CLAUDE:
            return ClaudeAdapter(agent)
        if agent.type == AgentType.CODEX:
            return CodexAdapter(agent)
        raise ValueError(f"No adapter available for agent type {agent.type}")

    def _get_session_lock(self, session_key: str) -> asyncio.Lock:
        lock = self._session_locks.get(session_key)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[session_key] = lock
        return lock

    async def _send_message(self, channel: str, thread_ts: str, text: str) -> None:
        if not self._chat_adapter:
            LOGGER.warning("Chat adapter not bound; dropping message: %s", text)
            return
        await self._chat_adapter.send_message(channel=channel, thread_ts=thread_ts, text=text)
