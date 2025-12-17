"""Handler for automatic project creation from Slack."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional

from ..config import Config, load_config
from ..project_creation import ProjectCreationRequest, ProjectCreationService
from ...github import GitHubManager

LOGGER = logging.getLogger(__name__)

# Type alias for the message sender callback
SendMessage = Callable[[str, str, str], Awaitable[Optional[str]]]


@dataclass
class PendingProjectCreation:
    """Tracks a pending project creation prompt."""

    channel_id: str
    channel_name: str
    thread_ts: str
    created_at: float


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
            f"I couldn't find a project named **{channel_name}**. Is this a new idea?!?!\n\n"
            "Reply with **Y** to create it, or **N** to cancel.",
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
        Handle a potential Y/N response to a pending project creation prompt.

        Args:
            channel_id: The channel ID
            text: The message text
            send_message: Callback to send messages

        Returns:
            Tuple of (was_handled, new_config_if_created)
            - was_handled: True if this was a response to a pending prompt
            - new_config_if_created: New Config if project was created, None otherwise
        """
        pending = self._pending_projects.get(channel_id)
        if not pending:
            return False, None

        response = text.strip().lower()

        if response in ("y", "yes"):
            del self._pending_projects[channel_id]
            new_config = await self._handle_approval(pending, send_message)
            return True, new_config
        elif response in ("n", "no"):
            del self._pending_projects[channel_id]
            await self._handle_rejection(pending, send_message)
            return True, None
        else:
            # Not a y/n response, remind them
            await send_message(
                pending.channel_id,
                pending.thread_ts,
                f"Please reply with **Y** to create project **{pending.channel_name}**, or **N** to cancel.",
            )
            return True, None

    async def _handle_approval(
        self,
        pending: PendingProjectCreation,
        send_message: SendMessage,
    ) -> Optional[Config]:
        """
        Handle user approving project creation.

        Returns:
            New Config if successful, None on failure
        """
        await send_message(
            pending.channel_id,
            pending.thread_ts,
            f"Creating project **{pending.channel_name}**...",
        )

        try:
            request = ProjectCreationRequest(
                project_id=pending.channel_name,
                channel_name=pending.channel_name,
                default_agent_id="claude",
            )

            await self._project_creator.create_project(request)

            # Reload config
            new_config = load_config(self._config_root)

            await send_message(
                pending.channel_id,
                pending.thread_ts,
                f"Okay great, I've set up **{pending.channel_name}**! "
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
