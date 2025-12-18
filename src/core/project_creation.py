"""Service for creating new projects with GitHub integration."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import Config
from .errors import (
    GitHubError,
    LocalDirNotGitRepoError,
    ProjectCreationError,
    ProjectNotFound,
    RepoExistsError,
)
from .models import GitHubRepoConfig, Project
from ..github import GitHubManager

LOGGER = logging.getLogger(__name__)

# Pattern to strip invalid characters from repo names (keep only letters, numbers, dashes)
REPO_NAME_INVALID_CHARS = re.compile(r"[^a-zA-Z0-9-]")


@dataclass
class ProjectCreationRequest:
    """Configuration for creating a new project."""

    project_id: str
    channel_name: str
    default_agent_id: str = "claude"
    default_base_branch: str = "main"


class ProjectCreationService:
    """Encapsulates project creation workflow."""

    def __init__(
        self,
        config: Config,
        github_manager: GitHubManager,
    ) -> None:
        self._config = config
        self._github = github_manager

    def update_config(self, config: Config) -> None:
        """Update the config reference."""
        self._config = config

    async def create_project(self, request: ProjectCreationRequest) -> Project:
        """
        Create a new project with local directory and GitHub repo.

        Flow:
        1. Sanitize channel name to get repo name
        2. Check if local directory exists:
           a. EXISTS + is git repo → just add to config
           b. EXISTS + not git repo → raise LocalDirNotGitRepoError
           c. DOESN'T EXIST → create dir, init git, create GitHub repo, push
        3. Update projects.yaml

        Returns:
            Created Project object

        Raises:
            ProjectCreationError: If any step fails
            RepoExistsError: If GitHub repo name already exists
            LocalDirNotGitRepoError: If local dir exists but isn't a git repo
        """
        repo_name = self._sanitize_repo_name(request.channel_name)
        LOGGER.info("Sanitized channel '%s' to repo name '%s'", request.channel_name, repo_name)

        local_path = self._config.base_dir / repo_name

        try:
            self._config.get_project_by_channel(request.channel_name)
            raise ProjectCreationError(f"Project '{request.channel_name}' is already configured")
        except ProjectNotFound:
            pass

        if local_path.exists():
            return await self._handle_existing_directory(
                local_path=local_path,
                repo_name=repo_name,
                request=request,
            )
        else:
            return await self._create_new_project(
                local_path=local_path,
                repo_name=repo_name,
                request=request,
            )

    async def _handle_existing_directory(
        self,
        local_path: Path,
        repo_name: str,
        request: ProjectCreationRequest,
    ) -> Project:
        """Handle the case where local directory already exists."""
        git_dir = local_path / ".git"

        if git_dir.exists() and git_dir.is_dir():
            LOGGER.info("Found existing git repo at %s, adding to config", local_path)

            # Try to parse owner from remote URL
            github_owner = None
            try:
                remote_url = await self._run_git(local_path, ["remote", "get-url", "origin"])
                if "github.com" in remote_url:
                    if remote_url.startswith("git@"):
                        parts = remote_url.split(":")[-1].replace(".git", "").split("/")
                    else:
                        parts = remote_url.replace(".git", "").split("/")[-2:]
                    if len(parts) >= 2:
                        github_owner = parts[0]
            except ProjectCreationError:
                pass

            if not github_owner:
                try:
                    github_owner = await self._get_github_owner()
                except GitHubError:
                    github_owner = "unknown"

            return await self._add_to_config(
                project_id=repo_name,
                channel_name=request.channel_name,
                local_path=local_path,
                github_owner=github_owner,
                repo_name=repo_name,
                default_base_branch=request.default_base_branch,
                default_agent_id=request.default_agent_id,
            )
        else:
            raise LocalDirNotGitRepoError(
                f"Directory '{local_path}' exists but isn't a git repository. "
                "This isn't supported yet, sorry :("
            )

    async def _create_new_project(
        self,
        local_path: Path,
        repo_name: str,
        request: ProjectCreationRequest,
    ) -> Project:
        """Create a completely new project with GitHub repo."""
        try:
            github_owner = await self._get_github_owner()

            local_path.mkdir(parents=True, exist_ok=False)
            LOGGER.info("Created local directory: %s", local_path)

            await self._init_git_repo(local_path, request.default_base_branch)
            LOGGER.info("Initialized git repository")

            repo_full_name = await self._create_github_repo(
                owner=github_owner,
                repo_name=repo_name,
                description=f"Created from Slack channel #{request.channel_name}",
            )
            LOGGER.info("Created GitHub repository: %s", repo_full_name)

            await self._create_initial_commit(
                local_path, repo_name, request.channel_name
            )
            LOGGER.info("Created initial commit")

            remote_url = f"git@github.com:{repo_full_name}.git"
            await self._push_to_github(
                local_path, remote_url, request.default_base_branch
            )
            LOGGER.info("Pushed to GitHub")

            project = await self._add_to_config(
                project_id=repo_name,
                channel_name=request.channel_name,
                local_path=local_path,
                github_owner=github_owner,
                repo_name=repo_name,
                default_base_branch=request.default_base_branch,
                default_agent_id=request.default_agent_id,
            )
            LOGGER.info("Updated projects.yaml")

            return project

        except (ProjectCreationError, RepoExistsError, LocalDirNotGitRepoError, GitHubError):
            self._cleanup_failed_creation(local_path)
            raise
        except Exception as e:
            self._cleanup_failed_creation(local_path)
            raise ProjectCreationError(
                f"Something unexpected happened while creating '{repo_name}'. "
                f"You'll need to check this when you're home. Sorry :( ({e})"
            ) from e

    def _sanitize_repo_name(self, channel_name: str) -> str:
        """
        Sanitize channel name to a valid GitHub repo name.

        Keeps only letters, numbers, and dashes.
        Strips leading/trailing dashes.
        """
        sanitized = REPO_NAME_INVALID_CHARS.sub("", channel_name).strip("-")

        if not sanitized:
            raise ProjectCreationError(
                f"Channel name '{channel_name}' results in an empty repo name after sanitization. "
                "Please rename the channel to include letters or numbers."
            )

        return sanitized

    async def _get_github_owner(self) -> str:
        """Get the GitHub owner/username for creating repos."""
        if not self._github.is_configured():
            raise GitHubError("GitHub token is not configured")

        def _get_user_login() -> str:
            user = self._github._client.get_user()
            return user.login

        return await asyncio.to_thread(_get_user_login)

    async def _init_git_repo(self, path: Path, default_branch: str) -> None:
        """Initialize a git repository."""
        await self._run_git(path, ["init"])
        await self._run_git(path, ["branch", "-M", default_branch])

    async def _create_github_repo(
        self,
        owner: str,
        repo_name: str,
        description: str,
    ) -> str:
        """
        Create a private GitHub repository.

        Returns:
            Full repository name (owner/repo)

        Raises:
            RepoExistsError: If the repo name already exists
            ProjectCreationError: For other GitHub API errors
        """

        def _create_repo() -> str:
            user = self._github._client.get_user()
            repo = user.create_repo(
                name=repo_name,
                description=description,
                private=True,
                auto_init=False,
            )
            return repo.full_name

        try:
            return await asyncio.to_thread(_create_repo)
        except Exception as e:
            error_str = str(e).lower()
            if "already exists" in error_str:
                raise RepoExistsError(
                    f"A GitHub repository named '{repo_name}' already exists. "
                    "Please rename the Slack channel and try again."
                ) from e
            raise ProjectCreationError(
                f"Something unexpected happened while creating the GitHub repository. "
                f"You'll need to check this when you're home. Sorry :( ({e})"
            ) from e

    async def _create_initial_commit(
        self,
        path: Path,
        project_id: str,
        channel_name: str,
    ) -> None:
        """Create initial README and commit."""
        readme = path / "README.md"
        readme.write_text(
            f"# {project_id}\n\nCreated from Slack channel #{channel_name}\n"
        )
        await self._run_git(path, ["add", "README.md"])
        await self._run_git(path, ["commit", "-m", "Initial commit"])

    async def _push_to_github(
        self,
        path: Path,
        remote_url: str,
        default_branch: str,
    ) -> None:
        """Add remote and push."""
        await self._run_git(path, ["remote", "add", "origin", remote_url])
        await self._run_git(path, ["push", "-u", "origin", default_branch])

    async def _add_to_config(
        self,
        project_id: str,
        channel_name: str,
        local_path: Path,
        github_owner: str,
        repo_name: str,
        default_base_branch: str,
        default_agent_id: str,
    ) -> Project:
        """Add project entry to projects.yaml."""
        projects_yaml = self._config.config_dir / "projects.yaml"

        with open(projects_yaml, "r") as f:
            data = yaml.safe_load(f) or {}

        if "projects" not in data:
            data["projects"] = {}

        try:
            relative_path = local_path.relative_to(self._config.base_dir)
        except ValueError:
            relative_path = local_path

        data["projects"][project_id] = {
            "path": str(relative_path),
            "default_agent": default_agent_id,
            "github": {
                "owner": github_owner,
                "repo": repo_name,
                "default_base_branch": default_base_branch,
            },
        }

        with open(projects_yaml, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        return Project(
            id=project_id,
            channel_name=channel_name,
            path=local_path,
            default_agent_id=default_agent_id,
            github=GitHubRepoConfig(
                owner=github_owner,
                repo=repo_name,
                default_base_branch=default_base_branch,
            ),
        )

    async def _run_git(self, cwd: Path, args: list[str]) -> str:
        """Run a git command asynchronously."""
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            raise ProjectCreationError(f"Git command failed: git {' '.join(args)}: {error_msg}")

        return stdout.decode().strip() if stdout else ""

    def _cleanup_failed_creation(self, path: Path) -> None:
        """Clean up local directory on failure."""
        if path.exists():
            try:
                shutil.rmtree(path)
                LOGGER.info("Cleaned up failed creation: %s", path)
            except Exception as e:
                LOGGER.warning("Failed to cleanup %s: %s", path, e)
