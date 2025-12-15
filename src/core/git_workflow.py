"""Git and GitHub workflow helpers used by the router."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

from ..agent_adapters import AgentResult
from ..github import GitHubManager
from ..github.client import EnsurePROptions
from .errors import GitHubError, SessionNotFound
from .models import Project, Session
from .conversation import SessionManager

LOGGER = logging.getLogger(__name__)


class GitWorkflowService:
    """Encapsulates git operations and PR publishing logic."""

    def __init__(
        self,
        github_manager: GitHubManager,
        session_manager: SessionManager,
    ) -> None:
        self._github_manager = github_manager
        self._session_manager = session_manager

    async def maybe_publish_code_changes(
        self,
        session: Session,
        project: Project,
        result: AgentResult,
        pr_title: str,
    ) -> Optional[str]:
        if not project.github or not self._github_manager.is_configured():
            LOGGER.debug("Skipping PR creation: no GitHub config")
            return None

        repo_path = session.project_path
        has_changes = bool(result.file_edits)
        if not has_changes:
            has_changes = await self._repo_has_changes(repo_path)

        if not has_changes:
            LOGGER.info("No file changes detected - skipping commit/push")
            return None

        if result.structured_output:
            LOGGER.info(
                "Structured output present: pr_title=%s, summary_items=%d",
                result.structured_output.pr_title,
                len(result.structured_output.pr_summary),
            )

        LOGGER.info("Changes detected - proceeding with commit and push")
        try:
            return await self._publish_branch_update(session, project, pr_title)
        except GitHubError as exc:
            LOGGER.exception("GitHub workflow failed for session %s", session.id)
            return f"GitHub integration failed: {exc}"
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            LOGGER.exception("Git command failed for session %s", session.id)
            message = detail or "Unknown git error."
            return f"Git command failed while preparing PR: {message}"

    async def setup_session_branch(self, session: Session, project: Project) -> None:
        if not project.github:
            return
        branch = f"remote-coder-{session.id}"
        repo_path = session.project_path
        rev_parse = await self._run_git(repo_path, ["rev-parse", "--verify", branch], check=False)
        if rev_parse.returncode == 0:
            await self._run_git(repo_path, ["checkout", branch])
            return

        base = project.github.default_base_branch
        await self._prepare_base_branch(repo_path, base, require_clean=True)
        await self._run_git(repo_path, ["checkout", "-B", branch, base])

    async def stash_changes(self, repo_path: Path) -> bool:
        await self._run_git(repo_path, ["add", "-A"])
        if not await self._repo_has_changes(repo_path):
            return False

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        await self._run_git(
            repo_path,
            ["stash", "push", "-m", f"remote-coder auto-stash {timestamp}"],
        )
        return True

    async def repo_has_changes(self, repo_path: Path) -> bool:
        result = await self._run_git(repo_path, ["status", "--porcelain"])
        return bool(result.stdout.strip())

    async def _publish_branch_update(self, session: Session, project: Project, pr_title: str) -> Optional[str]:
        branch = f"remote-coder-{session.id}"
        await self._ensure_branch(session.project_path, project, branch)
        await self._run_git(session.project_path, ["add", "-A"])
        if not await self._commit_changes(session.project_path, pr_title):
            return None
        await self._run_git(session.project_path, ["push", "-u", "origin", branch])

        existing_pr_number = self._get_existing_pr_number(session.id)

        pr_summary = session.session_context.get("pr_summary", [])
        if pr_summary and isinstance(pr_summary, list):
            summary_text = "\n".join(f"- {item}" for item in pr_summary)
            body = (
                f"{summary_text}\n\n---\nAutomated changes via Slack thread "
                f"{session.thread_ts} in channel {session.channel_id}."
            )
        else:
            body = (
                f"Automated changes requested via Slack thread {session.thread_ts} "
                f"in channel {session.channel_id}."
            )

        options = EnsurePROptions(
            title=pr_title,
            body=body,
        )
        pr_ref = await self._github_manager.ensure_pull_request(
            project=project,
            session_id=session.id,
            branch=branch,
            options=options,
            existing_number=existing_pr_number,
        )
        self._session_manager.set_pr_ref(pr_ref)
        return f"Pushed updates to branch `{branch}`\nLinked PR: {pr_ref.url}"

    async def _prepare_base_branch(self, repo_path: Path, base: str, require_clean: bool = False) -> None:
        if require_clean and await self._repo_has_changes(repo_path):
            raise GitHubError(
                "Working tree has local changes. Run `!stash` to stash them and start a new session."
            )
        await self._run_git(repo_path, ["fetch", "origin", base])
        show_ref = await self._run_git(repo_path, ["show-ref", "--verify", f"refs/heads/{base}"], check=False)
        if show_ref.returncode != 0:
            await self._run_git(repo_path, ["checkout", "-B", base, f"origin/{base}"])
        else:
            await self._run_git(repo_path, ["checkout", base])
            await self._run_git(repo_path, ["pull", "--ff-only", "origin", base])

    async def _commit_changes(self, repo_path: Path, message: str) -> bool:
        try:
            await self._run_git(repo_path, ["commit", "-m", message])
            return True
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").lower()
            if "nothing to commit" in stderr:
                return False
            raise

    async def _ensure_branch(self, repo_path: Path, project: Project, branch: str) -> None:
        rev_parse = await self._run_git(repo_path, ["rev-parse", "--verify", branch], check=False)
        if rev_parse.returncode == 0:
            await self._run_git(repo_path, ["checkout", branch])
            return

        base = project.github.default_base_branch if project.github else "main"
        dirty = await self._repo_has_changes(repo_path)
        if dirty:
            await self._run_git(repo_path, ["checkout", "-b", branch])
            return

        await self._prepare_base_branch(repo_path, base)
        await self._run_git(repo_path, ["checkout", "-B", branch, base])

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
