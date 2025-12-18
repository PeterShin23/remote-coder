"""Handler for automatic project creation from Slack."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional

from ..config import Config, load_config
from ..project_creation import ProjectCreationRequest, ProjectCreationService
from ...github import GitHubManager

LOGGER = logging.getLogger(__name__)

# Type alias for the message sender callback
SendMessage = Callable[[str, str, str], Awaitable[Optional[str]]]

# States for the project creation flow
STATE_AWAITING_CONFIRMATION = "awaiting_confirmation"
STATE_AWAITING_AGENT = "awaiting_agent"
STATE_AWAITING_MODEL = "awaiting_model"


@dataclass
class PendingProjectCreation:
    """Tracks a pending project creation prompt."""

    channel_id: str
    channel_name: str
    thread_ts: str
    created_at: float
    state: str = STATE_AWAITING_CONFIRMATION
    selected_agent_id: Optional[str] = None
    agent_options: List[str] = field(default_factory=list)
    model_options: List[str] = field(default_factory=list)


class ProjectCreationHandler:
    """Handles automatic project creation when messaging unknown channels."""

    def __init__(
        self,
        config: Config,
        github_manager: GitHubManager,
        config_root,
    ) -> None:
        self._config = config
        self._config_root = config_root
        self._pending_projects: Dict[str, PendingProjectCreation] = {}
        self._project_creator = ProjectCreationService(
            config=config,
            github_manager=github_manager,
        )

    def update_config(self, config: Config) -> None:
        """Update the config reference."""
        self._config = config
        self._project_creator.update_config(config)

    async def handle_missing_project(
        self,
        channel_id: str,
        channel_name: str,
        thread_ts: str,
        send_message: SendMessage,
    ) -> None:
        """
        Handle a message to a channel without a configured project.

        Sends a prompt asking the user if they want to create the project.
        """
        # Check if we already prompted for this channel
        if channel_id in self._pending_projects:
            LOGGER.debug("Project creation already pending for %s", channel_name)
            return

        # Send prompt message
        await send_message(
            channel_id,
            thread_ts,
            f"I couldn't find a project named `{channel_name}`. Is this a new idea?!?!\n\n"
            "Reply with \"Y\" to create it, or \"N\" to cancel.",
        )

        # Track pending creation
        self._pending_projects[channel_id] = PendingProjectCreation(
            channel_id=channel_id,
            channel_name=channel_name,
            thread_ts=thread_ts,
            created_at=time.time(),
        )

    async def handle_response(
        self,
        channel_id: str,
        text: str,
        send_message: SendMessage,
    ) -> tuple[bool, Optional[Config]]:
        """
        Handle a response to a pending project creation prompt.

        Returns:
            Tuple of (was_handled, new_config_if_created)
        """
        pending = self._pending_projects.get(channel_id)
        if not pending:
            return False, None

        response = text.strip().lower()

        if pending.state == STATE_AWAITING_CONFIRMATION:
            return await self._handle_confirmation_response(pending, response, send_message)
        elif pending.state == STATE_AWAITING_AGENT:
            return await self._handle_agent_response(pending, response, send_message)
        elif pending.state == STATE_AWAITING_MODEL:
            return await self._handle_model_response(pending, response, send_message)

        return False, None

    async def _handle_confirmation_response(
        self,
        pending: PendingProjectCreation,
        response: str,
        send_message: SendMessage,
    ) -> tuple[bool, Optional[Config]]:
        """Handle Y/N confirmation response."""
        if response in ("y", "yes"):
            await self._show_agent_options(pending, send_message)
            return True, None
        elif response in ("n", "no"):
            del self._pending_projects[pending.channel_id]
            await self._handle_rejection(pending, send_message)
            return True, None
        else:
            await send_message(
                pending.channel_id,
                pending.thread_ts,
                f"Please reply with \"Y\" to create project `{pending.channel_name}`, or \"N\" to cancel.",
            )
            return True, None

    async def _handle_agent_response(
        self,
        pending: PendingProjectCreation,
        response: str,
        send_message: SendMessage,
    ) -> tuple[bool, Optional[Config]]:
        """Handle agent selection response."""
        try:
            choice = int(response)
            if 1 <= choice <= len(pending.agent_options):
                pending.selected_agent_id = pending.agent_options[choice - 1]
                await self._show_model_options(pending, send_message)
                return True, None
        except ValueError:
            pass

        await send_message(
            pending.channel_id,
            pending.thread_ts,
            f"Please reply with the number corresponding to the agent.",
        )
        return True, None

    async def _handle_model_response(
        self,
        pending: PendingProjectCreation,
        response: str,
        send_message: SendMessage,
    ) -> tuple[bool, Optional[Config]]:
        """Handle model selection response."""
        try:
            choice = int(response)
            if 1 <= choice <= len(pending.model_options):
                selected_model = pending.model_options[choice - 1]
                del self._pending_projects[pending.channel_id]
                new_config = await self._create_project(
                    pending, pending.selected_agent_id, selected_model, send_message
                )
                return True, new_config
        except ValueError:
            pass

        await send_message(
            pending.channel_id,
            pending.thread_ts,
            f"Please reply with the number corresponding to the model.",
        )
        return True, None

    async def _show_agent_options(
        self,
        pending: PendingProjectCreation,
        send_message: SendMessage,
    ) -> None:
        """Show available agents for selection."""
        pending.agent_options = list(self._config.agents.keys())
        pending.state = STATE_AWAITING_AGENT

        lines = ["Which agent should I use for this project?\n"]
        for i, agent_id in enumerate(pending.agent_options, 1):
            lines.append(f"{i}. {agent_id}")
        lines.append("\nReply with the number.")

        await send_message(pending.channel_id, pending.thread_ts, "\n".join(lines))

    async def _show_model_options(
        self,
        pending: PendingProjectCreation,
        send_message: SendMessage,
    ) -> None:
        """Show available models for the selected agent."""
        agent = self._config.agents.get(pending.selected_agent_id)
        if agent and agent.models:
            pending.model_options = agent.models.get("available", [])
        else:
            pending.model_options = []

        if not pending.model_options:
            del self._pending_projects[pending.channel_id]
            new_config = await self._create_project(
                pending, pending.selected_agent_id, None, send_message
            )
            return

        pending.state = STATE_AWAITING_MODEL

        lines = [f"Which model for `{pending.selected_agent_id}`?\n"]
        for i, model in enumerate(pending.model_options, 1):
            lines.append(f"{i}. {model}")
        lines.append("\nReply with the number.")

        await send_message(pending.channel_id, pending.thread_ts, "\n".join(lines))

    async def _create_project(
        self,
        pending: PendingProjectCreation,
        agent_id: str,
        model: Optional[str],
        send_message: SendMessage,
    ) -> Optional[Config]:
        """
        Create the project with selected agent and model.

        Returns:
            New Config if successful, None on failure
        """
        model_str = f"/{model}" if model else ""
        await send_message(
            pending.channel_id,
            pending.thread_ts,
            f"Creating project `{pending.channel_name}` with `{agent_id} {model_str}`...",
        )

        try:
            request = ProjectCreationRequest(
                project_id=pending.channel_name,
                channel_name=pending.channel_name,
                default_agent_id=agent_id,
                default_model=model,
            )

            await self._project_creator.create_project(request)

            new_config = load_config(self._config_root)

            await send_message(
                pending.channel_id,
                pending.thread_ts,
                f"Okay great, I've set up `{pending.channel_name}`! "
                "What's this new idea? What do you want me to do?",
            )

            return new_config

        except Exception as e:
            LOGGER.exception("Failed to create project %s", pending.channel_name)
            await send_message(
                pending.channel_id,
                pending.thread_ts,
                f"Sorry, I couldn't create the project: {e}",
            )
            return None

    async def _handle_rejection(
        self,
        pending: PendingProjectCreation,
        send_message: SendMessage,
    ) -> None:
        """Handle user rejecting project creation."""
        await send_message(
            pending.channel_id,
            pending.thread_ts,
            "Okay, if the project name is different, then rename the channel "
            "and reload to try again. Otherwise, this channel won't be connected "
            "to any of your repositories.",
        )
