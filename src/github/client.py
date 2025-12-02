"""Lightweight GitHub client helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from github import Github
from github.PullRequest import PullRequest

from ..core.errors import GitHubError
from ..core.models import Project, PullRequestRef


@dataclass
class EnsurePROptions:
    title: str
    body: str


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
