"""CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from pathlib import Path
from typing import Sequence

from .chat_adapters.slack_adapter import SlackAdapter
from .core import Config, ConfigError, Router, SessionManager, load_config
from .core.config import resolve_config_dir
from .github import GitHubManager

LOGGER = logging.getLogger(__name__)


def cli(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        prog="remote-coder",
        description="Remote Coder - Slack-first daemon for controlling local coding agents",
    )
    parser.add_argument(
        "--config-dir",
        type=str,
        help="Directory containing .env, projects.yaml, and agents.yaml (default: ~/.remote-coder)",
    )

    # Add subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Init subcommand
    init_parser = subparsers.add_parser(
        "init",
        help="Initialize Remote Coder configuration interactively",
    )
    init_parser.add_argument(
        "--config-dir",
        type=str,
        help="Target config directory (default: ~/.remote-coder)",
    )

    args = parser.parse_args(argv)

    # Route to appropriate handler
    if args.command == "init":
        # Import here to avoid circular dependencies
        from .commands import run_init_command

        return run_init_command(args)
    else:
        # Default behavior: start daemon (backward compatible)
        config_dir = args.config_dir or os.getenv("REMOTE_CODER_CONFIG_DIR")

        try:
            asyncio.run(_run_async(config_dir))
        except ConfigError as exc:
            LOGGER.error("Configuration error: %s", exc)
            return 1
        except KeyboardInterrupt:
            LOGGER.info("Interrupted by user")
            return 130
        return 0


def run() -> None:
    """Backwards compatibility shim for older entrypoints."""
    cli()


async def _run_async(config_dir: str | Path | None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    resolved_dir = resolve_config_dir(config_dir)
    LOGGER.info("Using config directory: %s", resolved_dir)

    config: Config = load_config(resolved_dir)

    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    logging.getLogger().setLevel(log_level)

    LOGGER.info(
        "Loaded %s project(s) and %s agent(s)",
        len(config.projects),
        len(config.agents),
    )

    session_manager = SessionManager()
    github_manager = GitHubManager(config.github_token)
    router = Router(session_manager, config, github_manager, resolved_dir)
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


if __name__ == "__main__":
    raise SystemExit(cli())
