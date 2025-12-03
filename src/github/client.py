"""Lightweight GitHub client helpers."""

from __future__ import annotations

import asyncio
import logging
import requests
from dataclasses import dataclass
from typing import Any, List, Optional
from uuid import UUID

from github import Github
from github.PullRequest import PullRequest

from ..core.errors import GitHubError
from ..core.models import Project, PullRequestRef

LOGGER = logging.getLogger(__name__)


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

        # Use GraphQL to get review threads with resolved status
        try:
            return self._get_unresolved_comments_graphql(project, pull_number)
        except Exception as e:
            LOGGER.warning(f"GraphQL query failed: {e}, falling back to REST API (all comments)")
            # Fallback: include all review comments without filtering
            comments: List[PRComment] = []
            for comment in pull.get_review_comments():
                comments.append(self._to_pr_comment(comment))
            return comments

    def _get_unresolved_comments_graphql(
        self,
        project: Project,
        pull_number: int,
    ) -> List[PRComment]:
        """Use GitHub GraphQL API to fetch unresolved review threads."""
        if not self._token or not project.github:
            raise GitHubError("Missing token or GitHub config")

        query = """
        query($owner: String!, $repo: String!, $number: Int!) {
          repository(owner: $owner, name: $repo) {
            pullRequest(number: $number) {
              reviewThreads(first: 100) {
                nodes {
                  isResolved
                  comments(first: 1) {
                    nodes {
                      author {
                        login
                      }
                      body
                      path
                      line
                      startLine
                      url
                    }
                  }
                }
              }
            }
          }
        }
        """

        variables = {
            "owner": project.github.owner,
            "repo": project.github.repo,
            "number": pull_number,
        }

        response = requests.post(
            "https://api.github.com/graphql",
            json={"query": query, "variables": variables},
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            raise GitHubError(f"GraphQL errors: {data['errors']}")

        threads = data.get("data", {}).get("repository", {}).get("pullRequest", {}).get("reviewThreads", {}).get("nodes", [])

        comments: List[PRComment] = []
        resolved_count = 0
        thread_count = 0

        for thread in threads:
            thread_count += 1
            is_resolved = thread.get("isResolved", False)

            if is_resolved:
                resolved_count += 1
                continue

            # Get the first comment in the thread
            thread_comments = thread.get("comments", {}).get("nodes", [])
            if not thread_comments:
                continue

            comment_data = thread_comments[0]
            author = comment_data.get("author", {}).get("login", "unknown")
            body = comment_data.get("body", "")
            url = comment_data.get("url", "")
            path = comment_data.get("path")

            # Build position string
            position = None
            start_line = comment_data.get("startLine")
            line = comment_data.get("line")
            if start_line and line:
                position = f"{start_line}-{line}"
            elif line:
                position = str(line)

            comments.append(PRComment(
                author=author,
                body=body,
                url=url,
                path=path,
                position=position,
            ))

        LOGGER.info(f"Processed {thread_count} review threads: {resolved_count} resolved, {len(comments)} unresolved")
        return comments

    def _to_pr_comment(self, comment: Any) -> PRComment:
        path = getattr(comment, "path", None)
        position = None
        start_line = getattr(comment, "start_line", None)
        line = getattr(comment, "line", None)
        if start_line and line:
            position = f"{start_line}-{line}"
        elif line:
            position = str(line)
        return PRComment(
            author=getattr(comment.user, "login", "unknown"),
            body=comment.body or "",
            url=getattr(comment, "html_url", ""),
            path=path,
            position=position,
        )

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
