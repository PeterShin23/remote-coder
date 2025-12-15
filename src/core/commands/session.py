"""Handlers for session management commands."""

from __future__ import annotations

import logging

from ..config import Config
from ..errors import AgentNotFound
from ..models import SessionStatus
from ..conversation import SessionManager
from .parser import ParsedCommand
from .base import BaseCommandHandler
from .context import CommandContext

LOGGER = logging.getLogger(__name__)


class SessionCommandHandler(BaseCommandHandler):
    """Implements commands that manipulate session state."""

    def __init__(
        self,
        session_manager: SessionManager,
        config: Config,
        send_message,
    ) -> None:
        super().__init__(send_message)
        self._session_manager = session_manager
        self._config = config

    def update_config(self, config: Config) -> None:
        self._config = config

    async def handle_use(self, command: ParsedCommand, context: CommandContext) -> None:
        LOGGER.info("Executing !use command in channel %s, thread %s", context.channel, context.thread_ts)
        if not command.args:
            await self._reply(context, "Usage: `!use <agent> [model]`")
            return

        agent_id = command.args[0].lower()
        model = command.args[1].lower() if len(command.args) > 1 else None

        try:
            agent = self._config.get_agent(agent_id)
        except AgentNotFound:
            await self._reply(context, f"Unknown agent `{agent_id}`")
            return

        if model:
            available_models = agent.models.get("available", [])
            if model not in available_models:
                models_list = ", ".join(available_models)
                await self._reply(
                    context,
                    f"Unknown model `{model}` for agent `{agent_id}`. Available: {models_list}",
                )
                return

        if not model and agent.models:
            model = agent.models.get("default")

        self._session_manager.set_active_agent(context.session.id, agent_id, agent.type, model)
        LOGGER.info("Switched session %s to agent %s model %s", context.session.id, agent_id, model)

        model_display = f" `{model}`" if model else ""
        await self._reply(context, f"Switched to `{agent_id}`{model_display}")

    async def handle_end(self, command: ParsedCommand, context: CommandContext) -> None:
        LOGGER.info("Executing !end command in channel %s, thread %s", context.channel, context.thread_ts)
        if context.session.status == SessionStatus.ENDED:
            await self._reply(context, "Session already ended.")
            return
        self._session_manager.update_status(context.session.id, SessionStatus.ENDED)
        LOGGER.info("Ended session %s", context.session.id)
        await self._reply(context, "Session ended. Start a new thread to begin again.")

    async def handle_status(self, command: ParsedCommand, context: CommandContext) -> None:
        LOGGER.debug("Executing !status command in channel %s, thread %s", context.channel, context.thread_ts)
        history = self._session_manager.get_conversation_history(context.session.id)
        status_lines = [
            f"Session ID: `{context.session.id}`",
            f"Project: `{context.session.project_id}`",
            f"Active agent: `{context.session.active_agent_id}` ({context.session.active_agent_type.value})",
            f"Messages stored: {len(history)}",
            f"Status: {context.session.status.value}",
        ]
        await self._reply(context, "\n".join(status_lines))
