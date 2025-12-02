"""Chat adapter abstraction."""

from __future__ import annotations

import abc


class IChatAdapter(abc.ABC):
    """Abstraction for chat platform integrations (Slack, Discord, etc.)."""

    @abc.abstractmethod
    async def send_message(self, channel: str, thread_ts: str, text: str) -> None:
        """Send a message to a channel/thread."""

    @abc.abstractmethod
    async def start(self) -> None:
        """Begin listening for events."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Shutdown the adapter."""
