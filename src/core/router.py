"""Routes Slack events to core logic."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional
from uuid import UUID

from ..chat_adapters.i_chat_adapter import IChatAdapter
from ..github import GitHubManager
from ..github.client import PRComment
from .agent_runner import AgentTaskRunner
from .commands.parser import ParsedCommand, parse_command
from .commands.catalog import CatalogCommandHandler
from .commands.context import CommandContext
from .commands.dispatcher import CommandDispatcher
from .commands.maintenance import MaintenanceCommandHandler
from .commands.project_creation import ProjectCreationHandler
from .commands.registry import CommandSpec
from .commands.review import ReviewCommandHandler
from .commands.session import SessionCommandHandler
from .config import Config, load_config
from .errors import GitHubError, ProjectNotFound, SessionNotFound
from .git_workflow import GitWorkflowService
from .conversation import InteractionClassifier, SessionManager
from .models import Project, Session, SessionStatus

LOGGER = logging.getLogger(__name__)

CommandHandler = Callable[[ParsedCommand, CommandContext], Awaitable[None]]


class Router:
    """Central orchestrator translating Slack messages into agent executions."""

    def __init__(
        self,
        session_manager: SessionManager,
        config: Config,
        github_manager: GitHubManager,
        config_root: Path,
    ) -> None:
        self._session_manager = session_manager
        self._config = config
        self._github_manager = github_manager
        self._config_root = Path(config_root)
        self._chat_adapter: Optional[IChatAdapter] = None
        self._adapter_cache: Dict[str, AgentAdapter] = {}
        self._session_locks: Dict[str, asyncio.Lock] = {}
        self.active_runs: Dict[str, Dict[str, Any]] = {}
        self._interaction_classifier = InteractionClassifier()
        self._command_dispatcher = CommandDispatcher()
        self._project_creation_handler = ProjectCreationHandler(
            config=self._config,
            github_manager=self._github_manager,
            config_root=self._config_root,
        )
        self._git_workflow = GitWorkflowService(
            github_manager=self._github_manager,
            session_manager=self._session_manager,
        )
        self._agent_runner = AgentTaskRunner(
            config=self._config,
            session_manager=self._session_manager,
            interaction_classifier=self._interaction_classifier,
            git_workflow=self._git_workflow,
            adapter_cache=self._adapter_cache,
            active_runs=self.active_runs,
            send_message=self._send_message,
        )
        self._session_commands = SessionCommandHandler(
            session_manager=self._session_manager,
            config=self._config,
            send_message=self._send_message,
        )
        self._catalog_commands = CatalogCommandHandler(
            config=self._config,
            dispatcher=self._command_dispatcher,
            send_message=self._send_message,
        )
        self._maintenance_commands = MaintenanceCommandHandler(
            session_manager=self._session_manager,
            config_loader=lambda: load_config(self._config_root),
            apply_new_config=self._apply_new_config,
            get_current_config=lambda: self._config,
            active_runs=self.active_runs,
            _repo_has_changes=self._git_workflow._repo_has_changes,
            stash_changes=self._git_workflow.stash_changes,
            setup_session_branch=self._git_workflow.setup_session_branch,
            send_message=self._send_message,
        )
        self._review_commands = ReviewCommandHandler(
            session_manager=self._session_manager,
            github_manager=self._github_manager,
            build_review_prompt=self._build_review_prompt,
            execute_agent_task=self._agent_runner.run,
            send_message=self._send_message,
        )
        self._command_handlers: Dict[str, CommandHandler] = {
            "session.use": self._session_commands.handle_use,
            "session.end": self._session_commands.handle_end,
            "session.status": self._session_commands.handle_status,
            "review.pending": self._review_commands.handle_review,
            "maintenance.purge": self._maintenance_commands.handle_purge,
            "catalog.agents": self._catalog_commands.handle_agents,
            "catalog.models": self._catalog_commands.handle_models,
            "maintenance.reload_projects": self._maintenance_commands.handle_reload_projects,
            "maintenance.stash": self._maintenance_commands.handle_stash,
            "catalog.help": self._catalog_commands.handle_help,
        }

    def bind_adapter(self, adapter: IChatAdapter) -> None:
        """Attach the chat adapter so the router can send replies."""

        self._chat_adapter = adapter

    def _apply_new_config(self, new_config: Config) -> None:
        self._config = new_config
        self._github_manager.update_token(new_config.github_token)
        self._adapter_cache.clear()
        self._session_commands.update_config(new_config)
        self._catalog_commands.update_config(new_config)
        self._agent_runner.update_config(new_config)
        self._project_creation_handler.update_config(new_config)

        if self._chat_adapter and hasattr(self._chat_adapter, "update_allowed_users"):
            try:
                self._chat_adapter.update_allowed_users(new_config.slack_allowed_user_ids)
            except Exception:  # pragma: no cover - defensive
                LOGGER.warning("Failed to update Slack allowed users during config reload", exc_info=True)

    async def handle_message(self, event: Dict[str, Any]) -> None:
        channel_id = event.get("channel")
        channel_lookup = event.get("channel_name") or channel_id
        text = (event.get("text") or "").strip()
        thread_ts = event.get("thread_ts") or event.get("ts")

        if not channel_id or not thread_ts:
            LOGGER.debug("Ignoring Slack event missing channel or thread")
            return

        # Check if this is a response to a pending project creation prompt
        was_handled, new_config = await self._project_creation_handler.handle_response(
            channel_id, text, self._send_message
        )
        if was_handled:
            if new_config:
                self._apply_new_config(new_config)
            return

        try:
            project = self._config.get_project_by_channel(channel_lookup)
        except ProjectNotFound:
            LOGGER.warning("No project mapping for channel %s", channel_lookup)
            await self._project_creation_handler.handle_missing_project(
                channel_id, channel_lookup, thread_ts, self._send_message
            )
            return

        session, created = self._get_or_create_session(project, channel_id, thread_ts)

        command = parse_command(text)
        command_spec: Optional[CommandSpec] = None
        if command:
            command_spec = self._command_dispatcher.get_spec(command.name)
            if not command_spec:
                await self._send_message(
                    channel_id,
                    thread_ts,
                    f"Unknown command `{command.name}`. Use `!help` to see supported commands.",
                )
                return
        else:
            command = self._command_dispatcher.parse_bot_command(text)
            if command:
                command_spec = self._command_dispatcher.get_spec(command.name)

        if command and command_spec:
            await self._handle_command(command, command_spec, session, project, channel_id, thread_ts)
            return

        if not text:
            LOGGER.debug("Ignoring empty Slack message in %s", channel_lookup)
            return

        if session.status == SessionStatus.ENDED:
            await self._send_message(
                channel_id,
                thread_ts,
                "This session has ended. Start a new Slack thread to begin another run.",
            )
            return

        lock = self._get_session_lock(str(session.id))
        async with lock:
            await self._run_agent_interaction(session, project, channel_id, thread_ts, text, created)

    def _get_or_create_session(self, project: Project, channel_id: str, thread_ts: str) -> tuple[Session, bool]:
        try:
            return self._session_manager.get_by_thread(channel_id, thread_ts), False
        except SessionNotFound:
            default_agent = self._config.get_agent(project.default_agent_id)
            # Get default model for the agent
            default_model = default_agent.models.get("default") if default_agent.models else None
            session = self._session_manager.create_session(
                project=project,
                channel_id=channel_id,
                thread_ts=thread_ts,
                agent_id=default_agent.id,
                agent_type=default_agent.type,
                active_model=default_model,
            )
            return session, True

    async def _run_agent_interaction(
        self,
        session: Session,
        project: Project,
        channel_id: str,
        thread_ts: str,
        user_text: str,
        session_created: bool,
        ) -> None:
        if session_created:
            model_display = f" `{session.active_model}`" if session.active_model else ""
            await self._send_message(
                channel_id,
                thread_ts,
                f"Starting session for `{project.id}` with `{session.active_agent_id}`{model_display}. "
                "Send a message with your request, or use `!help` for common commands.",
            )
            try:
                await self._git_workflow.setup_session_branch(session, project)
            except GitHubError as exc:
                await self._send_message(
                    channel_id,
                    thread_ts,
                    f"Failed to prepare session branch: {exc}",
                )
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or str(exc)).strip()
                await self._send_message(
                    channel_id,
                    thread_ts,
                    f"Failed to prepare session branch: {detail or 'git error'}",
                )
            return

        await self._agent_runner.run(session, project, channel_id, thread_ts, user_text)

    async def _handle_command(
        self,
        command: ParsedCommand,
        spec: CommandSpec,
        session: Session,
        project: Project,
        channel_id: str,
        thread_ts: str,
    ) -> None:
        handler = self._command_handlers.get(spec.handler_id)
        if not handler:
            LOGGER.error("No handler registered for command %s (%s)", command.name, spec.handler_id)
            await self._send_message(channel_id, thread_ts, f"No handler found for `{command.name}`.")
            return
        context = CommandContext(
            session=session,
            project=project,
            channel=channel_id,
            thread_ts=thread_ts,
        )
        await handler(command, context)


    def _build_review_prompt(self, pr_url: str, comments: list[PRComment]) -> str:
        lines = [
            f"The pull request to update is: {pr_url}",
            "Address each unresolved review comment by making code changes, running relevant validations, "
            "and marking the comment as resolved via the updates you push.",
            "",
            "Comments:",
        ]
        for idx, comment in enumerate(comments, start=1):
            location = comment.path or "unknown file"
            if comment.position:
                location = f"{location} (line {comment.position})"
            body = comment.body.strip().replace("\n", " ")
            lines.append(f"{idx}. {comment.author} - {location}: {body}")
        lines.append(
            "Focus on implementing the requested changes, keeping git history clean, and summarizing what you fixed."
        )
        return "\n".join(lines)

    def _get_session_pr_title(self, session: Session) -> str:
        context_title = session.session_context.get("pr_title")
        if isinstance(context_title, str) and context_title.strip():
            return context_title.strip()
        return f"Remote Coder updates for session {session.id}"

    def _get_session_lock(self, session_key: str) -> asyncio.Lock:
        lock = self._session_locks.get(session_key)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[session_key] = lock
        return lock

    async def _send_message(
        self, channel: str, thread_ts: str, text: str
    ) -> Optional[str]:
        if not self._chat_adapter:
            LOGGER.warning("Chat adapter not bound; dropping message: %s", text)
            return None
        return await self._chat_adapter.send_message(
            channel=channel, thread_ts=thread_ts, text=text
        )
