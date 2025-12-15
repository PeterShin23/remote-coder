"""Handlers for maintenance-focused commands."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Awaitable, Callable, Dict

from .parser import ParsedCommand
from ..config import Config
from ..errors import ConfigError, GitHubError
from ..models import Project, Session
from ..conversation import SessionManager
from .base import BaseCommandHandler
from .context import CommandContext

LOGGER = logging.getLogger(__name__)


ReloadConfigFn = Callable[[], Config]
ApplyConfigFn = Callable[[Config], None]
HasChangesFn = Callable[[Path], Awaitable[bool]]
StashFn = Callable[[Path], Awaitable[bool]]
SetupBranchFn = Callable[[Session, Project], Awaitable[None]]


class MaintenanceCommandHandler(BaseCommandHandler):
    """Implements reload, purge, and stash commands."""

    def __init__(
        self,
        *,
        session_manager: SessionManager,
        config_loader: ReloadConfigFn,
        apply_new_config: ApplyConfigFn,
        get_current_config: Callable[[], Config],
        active_runs: Dict[str, Dict[str, object]],
        _repo_has_changes: HasChangesFn,
        stash_changes: StashFn,
        setup_session_branch: SetupBranchFn,
        send_message,
    ) -> None:
        super().__init__(send_message)
        self._session_manager = session_manager
        self._config_loader = config_loader
        self._apply_new_config = apply_new_config
        self._get_current_config = get_current_config
        self._active_runs = active_runs
        self._repo_has_changes = _repo_has_changes
        self._stash_changes = stash_changes
        self._setup_session_branch = setup_session_branch

    async def handle_reload_projects(self, command: ParsedCommand, context: CommandContext) -> None:
        LOGGER.info("Executing !reload-projects command in channel %s, thread %s", context.channel, context.thread_ts)
        try:
            new_config = self._config_loader()
        except ConfigError as exc:
            await self._reply(context, f"Failed to reload config: {exc}")
            return

        old_config = self._get_current_config()
        self._apply_new_config(new_config)

        slack_restart_note = ""
        if (
            old_config.slack_bot_token != new_config.slack_bot_token
            or old_config.slack_app_token != new_config.slack_app_token
        ):
            slack_restart_note = " (Slack tokens changed; restart the daemon for changes to take effect.)"

        await self._reply(
            context,
            f"Reloaded configuration: {len(new_config.projects)} project(s), {len(new_config.agents)} agent(s)."
            f"{slack_restart_note}",
        )

    async def handle_purge(self, command: ParsedCommand, context: CommandContext) -> None:
        LOGGER.info("Executing !purge command in channel %s, thread %s", context.channel, context.thread_ts)

        num_cancelled = 0
        if self._active_runs:
            LOGGER.info("Cancelling %d active agent run(s)", len(self._active_runs))
            tasks_to_cancel = []
            for run_info in list(self._active_runs.values()):
                task = run_info.get("task")
                if task and not getattr(task, "done", lambda: True)():
                    task.cancel()
                    tasks_to_cancel.append(task)

            if tasks_to_cancel:
                await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

            num_cancelled = len(self._active_runs)
            self._active_runs.clear()
        else:
            LOGGER.info("No active agent runs to cancel")

        num_sessions = self._session_manager.clear_all()
        if num_sessions > 0:
            LOGGER.info("Cleared %d session(s)", num_sessions)
        else:
            LOGGER.info("No sessions to clear")

        if num_cancelled > 0 or num_sessions > 0:
            message = (
                f"Stopped {num_cancelled} running agent task(s) and cleared {num_sessions} session(s). "
                "Remote Coder is now in a clean state."
            )
        else:
            message = "No active agent tasks. All sessions cleared. Remote Coder is in a clean state."

        LOGGER.info("Purge completed: cancelled %d task(s), cleared %d session(s)", num_cancelled, num_sessions)
        await self._reply(context, message)

    async def handle_stash(self, command: ParsedCommand, context: CommandContext) -> None:
        LOGGER.info("Executing !stash command in channel %s, thread %s", context.channel, context.thread_ts)

        _repo_has_changes = await self._repo_has_changes(context.project.path)
        if not _repo_has_changes:
            await self._reply(context, "No local changes to stash.")
            return

        try:
            stashed = await self._stash_changes(context.project.path)
            if not stashed:
                await self._reply(context, "No changes were stashed.")
                return
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            await self._reply(context, f"Failed to stash changes: {detail or 'git error'}")
            return

        await self._reply(context, "Local changes stashed. Run `git stash pop` later to restore them.")

        try:
            await self._setup_session_branch(context.session, context.project)
            await self._reply(context, "Session branch ready. Send your request to begin.")
        except (GitHubError, subprocess.CalledProcessError) as exc:
            detail = (
                exc if isinstance(exc, GitHubError) else (exc.stderr or exc.stdout or str(exc)).strip() or "git error"
            )
            await self._reply(context, f"Failed to prepare session branch: {detail}")
