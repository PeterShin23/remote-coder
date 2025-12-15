"""Handlers for catalog-style commands (help, agents, models)."""

from __future__ import annotations

from .parser import ParsedCommand
from ..config import Config
from .base import BaseCommandHandler
from .context import CommandContext
from .dispatcher import CommandDispatcher


class CatalogCommandHandler(BaseCommandHandler):
    """Operations that list available agents/models/help text."""

    def __init__(
        self,
        config: Config,
        dispatcher: CommandDispatcher,
        send_message,
    ) -> None:
        super().__init__(send_message)
        self._config = config
        self._dispatcher = dispatcher

    def update_config(self, config: Config) -> None:
        self._config = config

    async def handle_agents(self, command: ParsedCommand, context: CommandContext) -> None:
        agent_lines = ["Available agents:"]
        for _, agent in self._config.agents.items():
            agent_lines.append(f"- `{agent.type.value}`")
        await self._reply(context, "\n".join(agent_lines))

    async def handle_models(self, command: ParsedCommand, context: CommandContext) -> None:
        lines = ["Available models by agent:"]
        for agent_id, agent in self._config.agents.items():
            if agent.models:
                default = agent.models.get("default", "")
                available = agent.models.get("available", [])
                if available:
                    models_str = ", ".join(f"`{m}`" for m in available)
                    default_marker = f" (default: `{default}`)" if default else ""
                    lines.append(f"- `{agent_id}`: {models_str}{default_marker}")
                else:
                    lines.append(f"- `{agent_id}`: No models configured")
            else:
                lines.append(f"- `{agent_id}`: No models configured")
        await self._reply(context, "\n".join(lines))

    async def handle_help(self, command: ParsedCommand, context: CommandContext) -> None:
        lines = self._dispatcher.build_help_lines()
        await self._reply(context, "\n".join(lines))
