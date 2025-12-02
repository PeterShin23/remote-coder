"""Routes Slack events to core logic."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, Optional
from uuid import UUID

from ..chat_adapters.i_chat_adapter import IChatAdapter
from .config import Config
from .errors import AgentNotFound, ProcessError, ProjectNotFound, SessionNotFound
from ..agents.process_manager import ProcessManager
from .session_manager import SessionManager
from .models import Project, Session, SessionStatus
from .command_parser import ParsedCommand, parse_command

LOGGER = logging.getLogger(__name__)

OutputCallback = Callable[[str, str], Awaitable[None]]


class Router:
    def __init__(
        self,
        session_manager: SessionManager,
        process_manager: ProcessManager,
        config: Config,
    ) -> None:
        self._session_manager = session_manager
        self._process_manager = process_manager
        self._config = config
        self._chat_adapter: Optional[IChatAdapter] = None
        self._output_callbacks: Dict[UUID, OutputCallback] = {}
        self._busy_sessions: Dict[UUID, bool] = {}

    def bind_adapter(self, adapter: IChatAdapter) -> None:
        """Attach the chat adapter so the router can send replies."""

        self._chat_adapter = adapter

    async def handle_message(self, event: Dict[str, Any]) -> None:
        channel_id = event.get("channel")
        channel_lookup = event.get("channel_name") or channel_id
        user = event.get("user")
        text = (event.get("text") or "").strip()
        thread_ts = event.get("thread_ts") or event.get("ts")

        LOGGER.info(
            "Received message in channel %s from user %s: %s",
            channel_lookup,
            user,
            text,
        )

        if not channel_id or not thread_ts:
            LOGGER.debug("Missing channel or thread timestamp, ignoring event")
            return

        try:
            project = self._config.get_project_by_channel(channel_lookup)
        except ProjectNotFound:
            LOGGER.warning("No project mapping for channel %s", channel_lookup)
            return

        session = await self._get_or_create_session(project, channel_id, thread_ts)

        command = parse_command(text)
        if command:
            await self._handle_command(command, session, project, channel_id, thread_ts)
            return

        agent = self._config.get_agent(session.active_agent_id)

        try:
            await self._process_manager.ensure_process(
                session.id,
                project,
                agent,
                self._get_output_callback(session.id, channel_id, thread_ts),
            )
        except ProcessError as exc:
            LOGGER.exception("Failed to start process for agent %s", agent.id)
            await self._send_message(
                channel_id,
                thread_ts,
                f"Failed to start `{agent.id}`: {exc}",
            )
            return

        if not text:
            return

        if self._busy_sessions.get(session.id):
            await self._send_message(
                channel_id,
                thread_ts,
                "Agent is still working on the previous request. Please wait or end the session.",
            )
            return

        self._set_busy(session.id, True)

        try:
            await self._process_manager.send_to_process(session.id, text)
        except ProcessError as exc:
            LOGGER.exception("Failed to send input to process")
            self._set_busy(session.id, False)
            await self._send_message(
                channel_id,
                thread_ts,
                f"Failed to send message to `{agent.id}`: {exc}",
            )

    async def _get_or_create_session(
        self,
        project: Project,
        channel_id: str,
        thread_ts: str,
    ) -> Session:
        try:
            return self._session_manager.get_by_thread(channel_id, thread_ts)
        except SessionNotFound:
            session = self._session_manager.create_session(
                project_id=project.id,
                channel=channel_id,
                thread_ts=thread_ts,
                agent_id=project.default_agent_id,
            )
            await self._send_message(
                channel_id,
                thread_ts,
                f"Starting session with `{session.active_agent_id}` for project `{project.id}`",
            )
            return session

    def _get_output_callback(
        self,
        session_id: UUID,
        channel_id: str,
        thread_ts: str,
    ) -> OutputCallback:
        callback = self._output_callbacks.get(session_id)
        if callback:
            return callback

        async def _emit(stream_name: str, text: str) -> None:
            self._set_busy(session_id, False)
            prefix = "" if stream_name == "stdout" else f"[{stream_name}] "
            await self._send_message(channel_id, thread_ts, f"{prefix}{text}")

        self._output_callbacks[session_id] = _emit
        return _emit

    async def _send_message(self, channel: str, thread_ts: str, text: str) -> None:
        if not self._chat_adapter:
            LOGGER.warning("Chat adapter not bound; dropping message: %s", text)
            return
        await self._chat_adapter.send_message(channel=channel, thread_ts=thread_ts, text=text)

    async def _handle_command(
        self,
        command: ParsedCommand,
        session: Session,
        project: Project,
        channel_id: str,
        thread_ts: str,
    ) -> None:
        if command.name == "switch":
            await self._command_switch_agent(command, session, project, channel_id, thread_ts)
        elif command.name == "end":
            await self._command_end_session(session, channel_id, thread_ts)
        elif command.name == "stop-all":
            await self._command_stop_all(channel_id, thread_ts)
        elif command.name == "stop-agent":
            await self._command_stop_agent(command, channel_id, thread_ts)
        else:
            await self._send_message(
                channel_id,
                thread_ts,
                f"Unknown command `{command.name}`",
            )

    async def _command_switch_agent(
        self,
        command: ParsedCommand,
        session: Session,
        project: Project,
        channel: str,
        thread_ts: str,
    ) -> None:
        if not command.args:
            await self._send_message(channel, thread_ts, "Usage: !switch <agent-id>")
            return
        agent_id = command.args[0]
        try:
            agent = self._config.get_agent(agent_id)
        except AgentNotFound:
            await self._send_message(channel, thread_ts, f"Unknown agent `{agent_id}`")
            return

        self._session_manager.update_active_agent(session.id, agent_id)
        await self._process_manager.stop_process(session.id)
        self._set_busy(session.id, False)
        await self._send_message(
            channel,
            thread_ts,
            f"Switching session to `{agent_id}`",
        )
        await self._process_manager.ensure_process(
            session.id,
            project,
            agent,
            self._get_output_callback(session.id, channel, thread_ts),
        )

    async def _command_end_session(self, session: Session, channel: str, thread_ts: str) -> None:
        await self._process_manager.stop_process(session.id)
        self._session_manager.update_status(session.id, SessionStatus.ENDED)
        self._set_busy(session.id, False)
        await self._send_message(channel, thread_ts, "Session ended and agent stopped.")

    async def _command_stop_all(self, channel: str, thread_ts: str) -> None:
        stopped_sessions = await self._process_manager.stop_all_processes()
        for session_id in stopped_sessions:
            self._set_busy(session_id, False)
        await self._send_message(
            channel,
            thread_ts,
            f"Stopped {len(stopped_sessions)} running agent process(es).",
        )

    async def _command_stop_agent(self, command: ParsedCommand, channel: str, thread_ts: str) -> None:
        if not command.args:
            await self._send_message(channel, thread_ts, "Usage: !stop-agent <agent-id>")
            return
        agent_id = command.args[0]
        stopped_sessions = await self._process_manager.stop_processes_by_agent(agent_id)
        for session_id in stopped_sessions:
            self._set_busy(session_id, False)
        await self._send_message(
            channel,
            thread_ts,
            f"Stopped {len(stopped_sessions)} process(es) for agent `{agent_id}`",
        )

    def _set_busy(self, session_id: UUID, value: bool) -> None:
        if value:
            self._busy_sessions[session_id] = True
        else:
            self._busy_sessions.pop(session_id, None)
