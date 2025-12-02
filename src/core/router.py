"""Routes Slack events to core logic."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Sequence
from uuid import UUID

from ..agent_adapters import AgentAdapter, AgentResult, ClaudeAdapter, CodexAdapter
from ..chat_adapters.i_chat_adapter import IChatAdapter
from ..github import GitHubManager
from ..github.client import EnsurePROptions
from .command_parser import MENTION_PREFIX, ParsedCommand, parse_command
from .config import Config
from .errors import AgentNotFound, GitHubError, ProjectNotFound, SessionNotFound
from .models import Agent, AgentType, Project, Session, SessionStatus
from .session_manager import SessionManager

LOGGER = logging.getLogger(__name__)

CODE_TASK_WRAPPER = """You are Remote Coder, an autonomous developer working inside the user's repository.

1. Carefully read the latest Slack request and decide whether it requires code changes.
2. If it does, plan the steps, edit the files directly, and ensure the work is ready for a pull request (run relevant tests/linters when needed).
3. Summarize the changes you made in a concise, user-friendly way. Mention any follow-up work or tests the user should run.
4. If no code changes are required, explain why and offer guidance instead of editing files.
5. Never fabricate results or skip steps—only describe what you actually verified or changed.
"""


class Router:
    """Central orchestrator translating Slack messages into agent executions."""

    def __init__(
        self,
        session_manager: SessionManager,
        config: Config,
        github_manager: GitHubManager,
    ) -> None:
        self._session_manager = session_manager
        self._config = config
        self._github_manager = github_manager
        self._chat_adapter: Optional[IChatAdapter] = None
        self._adapter_cache: Dict[str, AgentAdapter] = {}
        self._session_locks: Dict[str, asyncio.Lock] = {}

    def bind_adapter(self, adapter: IChatAdapter) -> None:
        """Attach the chat adapter so the router can send replies."""

        self._chat_adapter = adapter

    async def handle_message(self, event: Dict[str, Any]) -> None:
        channel_id = event.get("channel")
        channel_lookup = event.get("channel_name") or channel_id
        text = (event.get("text") or "").strip()
        thread_ts = event.get("thread_ts") or event.get("ts")

        if not channel_id or not thread_ts:
            LOGGER.debug("Ignoring Slack event missing channel or thread")
            return

        try:
            project = self._config.get_project_by_channel(channel_lookup)
        except ProjectNotFound:
            LOGGER.warning("No project mapping for channel %s", channel_lookup)
            return

        session, created = self._get_or_create_session(project, channel_id, thread_ts)

        command = parse_command(text) or self._parse_bot_command(text)
        if command:
            await self._handle_command(command, session, project, channel_id, thread_ts)
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
            session = self._session_manager.create_session(
                project=project,
                channel_id=channel_id,
                thread_ts=thread_ts,
                agent_id=default_agent.id,
                agent_type=default_agent.type,
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
            await self._send_message(
                channel_id,
                thread_ts,
                f"Starting session for `{project.id}` with `{session.active_agent_id}`. "
                "Send a message with your request.",
            )
            await self._setup_session_branch(session, project)
            return

        agent = self._config.get_agent(session.active_agent_id)
        adapter = self._get_adapter(agent)

        await self._send_message(
            channel_id,
            thread_ts,
            f"Message received — running `{agent.id}` now.",
        )

        history_snapshot = self._session_manager.get_conversation_history(session.id)
        adapter_history = self._format_history_for_adapter(history_snapshot)
        task_text = self._build_task_text(history_snapshot, user_text)

        self._session_manager.append_user_message(session.id, user_text)

        try:
                result = await adapter.run(
                    task_text=task_text,
                    project_path=str(session.project_path),
                    session_id=str(session.id),
                conversation_history=adapter_history,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            LOGGER.exception("Adapter %s failed", agent.id)
            await self._send_message(
                channel_id,
                thread_ts,
                f"Failed to run `{agent.id}`: {exc}",
            )
            return

        response_text = result.output_text or "Agent completed with no textual output."
        if result.errors:
            response_text = f"{response_text}\n\nErrors:\n" + "\n".join(result.errors)
        if result.file_edits:
            edits_summary = ", ".join({edit.path for edit in result.file_edits})
            response_text = f"{response_text}\n\nDetected file edits: {edits_summary}"

        self._session_manager.append_agent_message(session.id, response_text)
        self._session_manager.update_session_context(session.id, result.session_context)

        pr_message = await self._maybe_publish_code_changes(session, project, result)
        if pr_message:
            response_text = f"{response_text}\n\n{pr_message}"

        await self._send_message(channel_id, thread_ts, response_text)

    def _parse_bot_command(self, text: str) -> Optional[ParsedCommand]:
        normalized = text.strip()
        normalized = MENTION_PREFIX.sub("", normalized, count=1)
        if normalized.lower().startswith("@remote-coder"):
            normalized = normalized[len("@remote-coder") :].strip()
        if normalized.lower().startswith("remote-coder"):
            normalized = normalized[len("remote-coder") :].strip()
        if not normalized:
            return None
        parts = normalized.split()
        if not parts:
            return None
        name = parts[0].lower()
        if name in {"use", "status", "end", "review"}:
            return ParsedCommand(name=name, args=parts[1:])
        return None

    async def _handle_command(
        self,
        command: ParsedCommand,
        session: Session,
        project: Project,
        channel_id: str,
        thread_ts: str,
    ) -> None:
        if command.name in {"switch", "use"}:
            await self._command_switch_agent(command, session, channel_id, thread_ts)
        elif command.name == "end":
            await self._command_end_session(session, channel_id, thread_ts)
        elif command.name == "status":
            await self._command_status(session, channel_id, thread_ts)
        elif command.name == "review":
            await self._command_review(session, project, channel_id, thread_ts)
        else:
            await self._send_message(channel_id, thread_ts, f"Unknown command `{command.name}`")

    async def _command_switch_agent(
        self,
        command: ParsedCommand,
        session: Session,
        channel: str,
        thread_ts: str,
    ) -> None:
        if not command.args:
            await self._send_message(channel, thread_ts, "Usage: use <agent-id>")
            return

        agent_id = command.args[0]
        try:
            agent = self._config.get_agent(agent_id)
        except AgentNotFound:
            await self._send_message(channel, thread_ts, f"Unknown agent `{agent_id}`")
            return

        self._session_manager.set_active_agent(session.id, agent_id, agent.type)
        await self._send_message(channel, thread_ts, f"Switched to `{agent_id}`")

    async def _command_end_session(self, session: Session, channel: str, thread_ts: str) -> None:
        if session.status == SessionStatus.ENDED:
            await self._send_message(channel, thread_ts, "Session already ended.")
            return
        self._session_manager.update_status(session.id, SessionStatus.ENDED)
        await self._send_message(channel, thread_ts, "Session ended. Start a new thread to begin again.")

    async def _command_status(self, session: Session, channel: str, thread_ts: str) -> None:
        history = self._session_manager.get_conversation_history(session.id)
        status_lines = [
            f"Session ID: `{session.id}`",
            f"Project: `{session.project_id}`",
            f"Active agent: `{session.active_agent_id}` ({session.active_agent_type.value})",
            f"Messages stored: {len(history)}",
            f"Status: {session.status.value}",
        ]
        await self._send_message(channel, thread_ts, "\n".join(status_lines))

    async def _command_review(
        self,
        session: Session,
        project: Project,
        channel: str,
        thread_ts: str,
    ) -> None:
        if not project.github:
            await self._send_message(channel, thread_ts, "This project has no GitHub configuration.")
            return
        if not self._github_manager.is_configured():
            await self._send_message(channel, thread_ts, "GitHub token is not configured; cannot fetch PR comments.")
            return

        try:
            pr_ref = self._session_manager.get_pr_ref(session.id)
        except SessionNotFound:
            await self._send_message(channel, thread_ts, "No pull request exists yet for this session.")
            return

        try:
            comments = await self._github_manager.get_unresolved_comments(project, pr_ref.number)
        except GitHubError as exc:
            await self._send_message(channel, thread_ts, f"Unable to fetch PR comments: {exc}")
            return

        if not comments:
            await self._send_message(channel, thread_ts, f"No unresolved review threads on {pr_ref.url}")
            return

        lines = [f"Unresolved review comments for {pr_ref.url}:"]
        for comment in comments[:10]:
            location = ""
            if comment.path:
                location = f" `{comment.path}`"
                if comment.position:
                    location += f" (line {comment.position})"
            snippet = comment.body.strip().replace("\n", " ")
            if len(snippet) > 300:
                snippet = snippet[:297] + "..."
            lines.append(f"- {comment.author}{location}: {snippet}\n  {comment.url}")

        if len(comments) > 10:
            lines.append(f"...and {len(comments) - 10} more comments.")
        await self._send_message(channel, thread_ts, "\n".join(lines))

    def _build_task_text(self, history: Sequence, user_text: str) -> str:
        recent = history[-5:]
        history_lines = [
            f"{'User' if msg.role == 'user' else 'Assistant'}: {msg.content}".strip()
            for msg in recent
            if msg.content
        ]
        context_block = "\n".join(history_lines) if history_lines else "No prior conversation."
        return (
            f"{CODE_TASK_WRAPPER}\n\n"
            f"Recent Slack context:\n{context_block}\n\n"
            f"Current user request:\n{user_text}\n"
            "Provide your answer below. If you changed code, summarize the edits and tests you ran."
        )

    def _format_history_for_adapter(self, history: Sequence) -> list[Dict[str, str]]:
        formatted: list[Dict[str, str]] = []
        for msg in history:
            formatted.append(
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                }
            )
        return formatted

    async def _maybe_publish_code_changes(
        self,
        session: Session,
        project: Project,
        result: AgentResult,
    ) -> Optional[str]:
        if not project.github or not self._github_manager.is_configured():
            return None

        repo_path = session.project_path
        has_changes = bool(result.file_edits)
        if not has_changes:
            has_changes = await self._repo_has_changes(repo_path)
        if not has_changes:
            return None

        try:
            return await self._publish_branch_update(session, project)
        except GitHubError as exc:
            LOGGER.exception("GitHub workflow failed for session %s", session.id)
            return f"GitHub integration failed: {exc}"
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            LOGGER.exception("Git command failed for session %s", session.id)
            message = detail or "Unknown git error."
            return f"Git command failed while preparing PR: {message}"

    async def _setup_session_branch(self, session: Session, project: Project) -> None:
        if not project.github:
            return
        branch = f"remote-coder-{session.id}"
        repo_path = session.project_path
        rev_parse = await self._run_git(repo_path, ["rev-parse", "--verify", branch], check=False)
        if rev_parse.returncode == 0:
            await self._run_git(repo_path, ["checkout", branch])
            return

        base = project.github.default_base_branch
        await self._run_git(repo_path, ["fetch", "origin", base])
        await self._run_git(repo_path, ["checkout", base])
        await self._run_git(repo_path, ["pull", "--ff-only", "origin", base])
        await self._run_git(repo_path, ["checkout", "-B", branch])

    async def _publish_branch_update(self, session: Session, project: Project) -> Optional[str]:
        branch = f"remote-coder-{session.id}"
        await self._ensure_branch(session.project_path, project, branch)
        await self._run_git(session.project_path, ["add", "-A"])
        if not await self._commit_changes(session.project_path, session):
            return None
        await self._run_git(session.project_path, ["push", "-u", "origin", branch])

        existing_pr_number = self._get_existing_pr_number(session.id)
        options = EnsurePROptions(
            title=f"Remote Coder updates for session {session.id}",
            body=(
                f"Automated changes requested via Slack thread {session.thread_ts} "
                f"in channel {session.channel_id}."
            ),
        )
        pr_ref = await self._github_manager.ensure_pull_request(
            project=project,
            session_id=session.id,
            branch=branch,
            options=options,
            existing_number=existing_pr_number,
        )
        self._session_manager.set_pr_ref(pr_ref)
        return f"Pushed updates to branch `{branch}` and linked PR: {pr_ref.url}"

    async def _repo_has_changes(self, repo_path: Path) -> bool:
        result = await self._run_git(repo_path, ["status", "--porcelain"])
        return bool(result.stdout.strip())

    async def _ensure_branch(self, repo_path: Path, project: Project, branch: str) -> None:
        # Check if branch exists locally
        rev_parse = await self._run_git(repo_path, ["rev-parse", "--verify", branch], check=False)
        if rev_parse.returncode == 0:
            await self._run_git(repo_path, ["checkout", branch])
            return

        base = project.github.default_base_branch if project.github else "main"
        dirty = await self._repo_has_changes(repo_path)
        if dirty:
            # Create the branch from the current HEAD (which already has the desired changes).
            await self._run_git(repo_path, ["checkout", "-b", branch])
            return

        await self._run_git(repo_path, ["fetch", "origin", base])
        await self._run_git(repo_path, ["checkout", base])
        await self._run_git(repo_path, ["pull", "--ff-only", "origin", base])
        await self._run_git(repo_path, ["checkout", "-B", branch, f"origin/{base}"])

    async def _commit_changes(self, repo_path: Path, session: Session) -> bool:
        message = f"Remote Coder update for session {session.id}"
        try:
            await self._run_git(repo_path, ["commit", "-m", message])
            return True
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").lower()
            if "nothing to commit" in stderr:
                return False
            raise

    def _get_existing_pr_number(self, session_id: UUID) -> Optional[int]:
        try:
            pr_ref = self._session_manager.get_pr_ref(session_id)
            return pr_ref.number
        except SessionNotFound:
            return None

    async def _run_git(self, cwd: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
        def _execute() -> subprocess.CompletedProcess:
            return subprocess.run(
                ["git", *args],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                check=check,
            )

        return await asyncio.to_thread(_execute)

    def _get_adapter(self, agent: Agent) -> AgentAdapter:
        cached = self._adapter_cache.get(agent.id)
        if cached:
            return cached

        adapter = self._build_adapter(agent)
        self._adapter_cache[agent.id] = adapter
        return adapter

    def _build_adapter(self, agent: Agent) -> AgentAdapter:
        if agent.type == AgentType.CLAUDE:
            return ClaudeAdapter(agent)
        if agent.type == AgentType.CODEX:
            return CodexAdapter(agent)
        raise ValueError(f"No adapter available for agent type {agent.type}")

    def _get_session_lock(self, session_key: str) -> asyncio.Lock:
        lock = self._session_locks.get(session_key)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[session_key] = lock
        return lock

    async def _send_message(self, channel: str, thread_ts: str, text: str) -> None:
        if not self._chat_adapter:
            LOGGER.warning("Chat adapter not bound; dropping message: %s", text)
            return
        await self._chat_adapter.send_message(channel=channel, thread_ts=thread_ts, text=text)
