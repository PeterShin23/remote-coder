"""Routes Slack events to core logic."""

from __future__ import annotations

import logging
from typing import Any, Dict

from .config import Config
from .session_manager import SessionManager

LOGGER = logging.getLogger(__name__)


class Router:
    def __init__(self, session_manager: SessionManager, config: Config) -> None:
        self._session_manager = session_manager
        self._config = config

    async def handle_message(self, event: Dict[str, Any]) -> None:
        channel = event.get("channel")
        user = event.get("user")
        text = event.get("text", "")
        thread_ts = event.get("thread_ts")

        LOGGER.info(
            "Received message in channel %s from user %s: %s",
            channel,
            user,
            text,
        )

        if thread_ts:
            LOGGER.info("Reply in thread %s", thread_ts)
        else:
            LOGGER.info("New top-level message (thread creation handled later)")
