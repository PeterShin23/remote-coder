"""Chat adapter abstraction."""

from __future__ import annotations

import abc
from typing import Optional


class IChatAdapter(abc.ABC):
    """Abstraction for chat platform integrations (Slack, Discord, etc.)."""

    @abc.abstractmethod
    async def send_message(
        self, channel: str, thread_ts: str, text: str
    ) -> Optional[str]:
        """Send a message to a channel/thread.

        Returns:
            The message timestamp/ID if available, None otherwise.
        """

    @abc.abstractmethod
    async def start(self) -> None:
        """Begin listening for events."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Shutdown the adapter."""
