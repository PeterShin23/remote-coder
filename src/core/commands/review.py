"""Handler for the `!review` command."""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from .parser import ParsedCommand
from ..errors import GitHubError, SessionNotFound
from ...github import GitHubManager
from ..models import Project, Session
from ..conversation import SessionManager
from .base import BaseCommandHandler
from .context import CommandContext

LOGGER = logging.getLogger(__name__)


BuildPromptFn = Callable[[str, list], str]
ExecuteAgentFn = Callable[[Session, Project, str, str, str], Awaitable[None]]


class ReviewCommandHandler(BaseCommandHandler):
    """Fetches unresolved PR comments and triggers agent review runs."""

    def __init__(
        self,
        *,
        session_manager: SessionManager,
        github_manager: GitHubManager,
        build_review_prompt: BuildPromptFn,
        execute_agent_task: ExecuteAgentFn,
        send_message,
    ) -> None:
        super().__init__(send_message)
        self._session_manager = session_manager
        self._github_manager = github_manager
        self._build_review_prompt = build_review_prompt
        self._execute_agent_task = execute_agent_task

    async def handle_review(self, command: ParsedCommand, context: CommandContext) -> None:
        LOGGER.info("Executing !review command in channel %s, thread %s", context.channel, context.thread_ts)
        if not context.project.github:
            await self._reply(context, "This project has no GitHub configuration.")
            return
        if not self._github_manager.is_configured():
            await self._reply(context, "GitHub token is not configured; cannot fetch PR comments.")
            return

        try:
            pr_ref = self._session_manager.get_pr_ref(context.session.id)
        except SessionNotFound:
            await self._reply(context, "No pull request exists yet for this session.")
            return

        try:
            comments = await self._github_manager.get_unresolved_comments(context.project, pr_ref.number)
        except GitHubError as exc:
            await self._reply(context, f"Unable to fetch PR comments: {exc}")
            return

        if not comments:
            await self._reply(context, f"No unresolved review threads on {pr_ref.url}")
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

        await self._reply(context, "\n".join(lines))

        prompt = self._build_review_prompt(pr_ref.url, comments)
        await self._execute_agent_task(
            context.session,
            context.project,
            context.channel,
            context.thread_ts,
            prompt,
        )
