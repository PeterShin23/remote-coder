"""CLI entry point."""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from dotenv import load_dotenv

from .core import Config, Router, SessionManager, load_config
from .chat_adapters.slack_adapter import SlackAdapter

LOGGER = logging.getLogger(__name__)


async def _run_async() -> None:
    load_dotenv()
    log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config: Config = load_config()
    LOGGER.info(
        "Loaded %s projects and %s agents",
        len(config.projects),
        len(config.agents),
    )

    session_manager = SessionManager()
    router = Router(session_manager, config)
    slack_adapter = SlackAdapter(
        bot_token=config.slack_bot_token,
        app_token=config.slack_app_token,
        allowed_user_ids=config.slack_allowed_user_ids,
        router=router,
    )
    router.bind_adapter(slack_adapter)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _request_shutdown() -> None:
        LOGGER.info("Shutdown requested")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            # Windows event loops before 3.11 do not support signal handlers.
            pass

    slack_task = asyncio.create_task(slack_adapter.start())
    LOGGER.info("Remote Coder daemon started")

    await stop_event.wait()
    await slack_adapter.stop()
    await slack_task
    LOGGER.info("Shutdown complete")


def run() -> None:
    asyncio.run(_run_async())


if __name__ == "__main__":
    run()
