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
from .errors import GitHubError, ProjectCreationError, ProjectNotFound
from .models import GitHubRepoConfig, Project
from ..github import GitHubManager

LOGGER = logging.getLogger(__name__)

# Valid project ID pattern: alphanumeric, hyphens, underscores
PROJECT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


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

        Steps:
        1. Validate project ID and ensure project doesn't exist
        2. Create local directory
        3. Initialize git repository
        4. Create GitHub repository (private)
        5. Add initial commit (README.md)
        6. Push to GitHub
        7. Update projects.yaml

        Returns:
            Created Project object

        Raises:
            ProjectCreationError: If any step fails
        """
        project_id = request.project_id

        # Validate project ID
        self._validate_project_id(project_id)

        local_path = self._config.base_dir / project_id

        # Validate project doesn't exist
        if local_path.exists():
            raise ProjectCreationError(f"Directory already exists: {local_path}")

        try:
            self._config.get_project_by_channel(project_id)
            raise ProjectCreationError(f"Project '{project_id}' is already configured")
        except ProjectNotFound:
            pass  # Good, doesn't exist

        try:
            # Get GitHub owner
            github_owner = await self._get_github_owner()

            # Create local directory
            local_path.mkdir(parents=True, exist_ok=False)
            LOGGER.info("Created local directory: %s", local_path)

            # Initialize git
            await self._init_git_repo(local_path, request.default_base_branch)
            LOGGER.info("Initialized git repository")

            # Create GitHub repo
            repo_full_name = await self._create_github_repo(
                owner=github_owner,
                repo_name=project_id,
                description=f"Created from Slack channel #{request.channel_name}",
            )
            LOGGER.info("Created GitHub repository: %s", repo_full_name)

            # Add initial commit
            await self._create_initial_commit(
                local_path, project_id, request.channel_name
            )
            LOGGER.info("Created initial commit")

            # Push to GitHub
            remote_url = f"git@github.com:{repo_full_name}.git"
            await self._push_to_github(
                local_path, remote_url, request.default_base_branch
            )
            LOGGER.info("Pushed to GitHub")

            # Update projects.yaml
            project = await self._add_to_config(
                project_id=project_id,
                channel_name=request.channel_name,
                local_path=local_path,
                github_owner=github_owner,
                repo_name=project_id,
                default_base_branch=request.default_base_branch,
                default_agent_id=request.default_agent_id,
            )
            LOGGER.info("Updated projects.yaml")

            return project

        except ProjectCreationError:
            # Cleanup and re-raise
            self._cleanup_failed_creation(local_path)
            raise
        except Exception as e:
            # Cleanup on unexpected failure
            self._cleanup_failed_creation(local_path)
            raise ProjectCreationError(
                f"Failed to create project '{project_id}': {e}"
            ) from e

    def _validate_project_id(self, project_id: str) -> None:
        """Validate project ID for safety and compatibility."""
        if not project_id:
            raise ProjectCreationError("Project ID cannot be empty")

        if len(project_id) > 100:
            raise ProjectCreationError("Project ID too long (max 100 characters)")

        # Prevent directory traversal
        if ".." in project_id or "/" in project_id or "\\" in project_id:
            raise ProjectCreationError(
                "Project ID cannot contain path separators or '..'"
            )

        if not PROJECT_ID_PATTERN.match(project_id):
            raise ProjectCreationError(
                "Project ID must start with alphanumeric and contain only "
                "alphanumeric characters, hyphens, or underscores"
            )

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
            raise GitHubError(f"Failed to create GitHub repository: {e}") from e

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

        # Load existing
        with open(projects_yaml, "r") as f:
            data = yaml.safe_load(f) or {}

        if "projects" not in data:
            data["projects"] = {}

        # Add new project - use relative path from base_dir
        try:
            relative_path = local_path.relative_to(self._config.base_dir)
        except ValueError:
            # If local_path is not relative to base_dir, use the full path
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

        # Write back
        with open(projects_yaml, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        # Create Project object
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
