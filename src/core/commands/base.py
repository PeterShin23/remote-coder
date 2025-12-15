"""Common utilities for command handlers."""

from __future__ import annotations

from typing import Awaitable, Callable, Optional

from .context import CommandContext

SendMessageFn = Callable[[str, str, str], Awaitable[None]]


class BaseCommandHandler:
    """Provides helper methods for replying to Slack."""

    def __init__(self, send_message: Optional[SendMessageFn] = None) -> None:
        self._send_message = send_message

    def bind_sender(self, send_message: SendMessageFn) -> None:
        self._send_message = send_message

    async def _reply(self, context: CommandContext, text: str) -> None:
        if not self._send_message:
            raise RuntimeError("send_message not bound for command handler")
        await self._send_message(context.channel, context.thread_ts, text)
