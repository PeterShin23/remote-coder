"""Lightweight GitHub client helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID

from github import Github
from github.PullRequest import PullRequest

from ..core.errors import GitHubError
from ..core.models import Project, PullRequestRef


@dataclass
class EnsurePROptions:
    title: str
    body: str


@dataclass
class PRComment:
    author: str
    body: str
    url: str
    path: Optional[str] = None
    position: Optional[str] = None


class GitHubManager:
    """Wrapper around PyGithub that exposes async helpers."""

    def __init__(self, token: Optional[str]) -> None:
        self._token = token
        self._client = Github(token) if token else None

    def is_configured(self) -> bool:
        return self._client is not None

    async def ensure_pull_request(
        self,
        project: Project,
        session_id: UUID,
        branch: str,
        options: EnsurePROptions,
        existing_number: Optional[int] = None,
    ) -> PullRequestRef:
        return await asyncio.to_thread(
            self._ensure_pull_request_sync,
            project,
            session_id,
            branch,
            options,
            existing_number,
        )

    async def get_unresolved_comments(
        self,
        project: Project,
        pull_number: int,
    ) -> List[PRComment]:
        return await asyncio.to_thread(
            self._get_unresolved_comments_sync,
            project,
            pull_number,
        )

    def _ensure_pull_request_sync(
        self,
        project: Project,
        session_id: UUID,
        branch: str,
        options: EnsurePROptions,
        existing_number: Optional[int],
    ) -> PullRequestRef:
        if not self._client:
            raise GitHubError("GitHub token is not configured.")
        if not project.github:
            raise GitHubError(f"Project {project.id} is missing GitHub metadata.")

        repo_name = f"{project.github.owner}/{project.github.repo}"
        repo = self._client.get_repo(repo_name)

        pull = None
        if existing_number:
            pull = repo.get_pull(existing_number)
            if pull.is_merged() or pull.state != "open":
                pull = None

        if not pull:
            pull = self._find_existing_pull(repo, project, branch)

        if not pull:
            pull = repo.create_pull(
                title=options.title,
                body=options.body,
                head=branch,
                base=project.github.default_base_branch,
            )

        return PullRequestRef(
            project_id=project.id,
            session_id=session_id,
            number=pull.number,
            url=pull.html_url,
            head_branch=pull.head.ref,
            base_branch=pull.base.ref,
        )

    def _get_unresolved_comments_sync(
        self,
        project: Project,
        pull_number: int,
    ) -> List[PRComment]:
        pull = self._get_pull(project, pull_number)
        if pull.is_merged():
            raise GitHubError(f"Pull request #{pull.number} is already merged.")
        if pull.state != "open":
            raise GitHubError(f"Pull request #{pull.number} is closed.")

        comments: List[PRComment] = []
        threads = pull.get_review_threads()
        for thread in threads:
            if self._thread_resolved(thread):
                continue
            for comment in getattr(thread, "comments", []):
                path = getattr(comment, "path", None)
                position = None
                start_line = getattr(comment, "start_line", None)
                line = getattr(comment, "line", None)
                if start_line and line:
                    position = f"{start_line}-{line}"
                elif line:
                    position = str(line)
                comments.append(
                    PRComment(
                        author=getattr(comment.user, "login", "unknown"),
                        body=comment.body or "",
                        url=comment.html_url,
                        path=path,
                        position=position,
                    )
                )
        return comments

    def _get_pull(self, project: Project, pull_number: int) -> PullRequest:
        if not self._client:
            raise GitHubError("GitHub token is not configured.")
        if not project.github:
            raise GitHubError(f"Project {project.id} is missing GitHub metadata.")
        repo_name = f"{project.github.owner}/{project.github.repo}"
        repo = self._client.get_repo(repo_name)
        try:
            return repo.get_pull(pull_number)
        except Exception as exc:
            raise GitHubError(f"Failed to load pull request #{pull_number}: {exc}") from exc

    def _thread_resolved(self, thread) -> bool:
        for attr in ("is_resolved", "resolved"):
            value = getattr(thread, attr, None)
            if callable(value):
                try:
                    return bool(value())
                except Exception:
                    continue
            if isinstance(value, bool):
                return value
        state = getattr(thread, "state", "").lower()
        return state == "resolved"

    def _find_existing_pull(self, repo, project: Project, branch: str) -> PullRequest | None:
        """Search for an open PR whose head matches branch."""
        try:
            pulls = repo.get_pulls(state="open", head=f"{project.github.owner}:{branch}")
        except Exception as exc:  # pragma: no cover - PyGithub raises generic exceptions
            raise GitHubError(f"Failed to query pull requests: {exc}") from exc

        for pull in pulls:
            if pull.head.ref == branch and not pull.is_merged():
                return pull
        return None
