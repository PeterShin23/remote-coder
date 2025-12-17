"""Tests for ProjectCreationService."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.config import Config
from src.core.errors import GitHubError, ProjectCreationError, ProjectNotFound
from src.core.models import Agent, AgentType, GitHubRepoConfig, Project, WorkingDirMode
from src.core.project_creation import ProjectCreationRequest, ProjectCreationService


@pytest.fixture
def test_config(tmp_path):
    """Create a test config with base_dir and config_dir."""
    base_dir = tmp_path / "projects"
    base_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Create projects.yaml
    projects_yaml = config_dir / "projects.yaml"
    projects_yaml.write_text(f'base_dir: "{base_dir}"\nprojects: {{}}\n')

    return Config(
        projects={},
        agents={
            "claude": Agent(
                id="claude",
                type=AgentType.CLAUDE,
                command=["claude"],
                working_dir_mode=WorkingDirMode.PROJECT,
            ),
        },
        slack_bot_token="bot-token",
        slack_app_token="app-token",
        slack_allowed_user_ids=["U123"],
        base_dir=base_dir,
        config_dir=config_dir,
        github_token="test-token",
    )


@pytest.fixture
def mock_github_manager():
    """Create a mock GitHubManager."""
    manager = MagicMock()
    manager.is_configured.return_value = True
    manager._client = MagicMock()

    # Mock user
    mock_user = MagicMock()
    mock_user.login = "test-user"

    # Mock repo creation
    mock_repo = MagicMock()
    mock_repo.full_name = "test-user/test-project"

    mock_user.create_repo.return_value = mock_repo
    manager._client.get_user.return_value = mock_user

    return manager


class TestProjectCreationService:
    """Tests for ProjectCreationService."""

    def test_validate_project_id_empty(self, test_config, mock_github_manager):
        """Test that empty project ID raises error."""
        service = ProjectCreationService(test_config, mock_github_manager)
        with pytest.raises(ProjectCreationError, match="cannot be empty"):
            service._validate_project_id("")

    def test_validate_project_id_too_long(self, test_config, mock_github_manager):
        """Test that overly long project ID raises error."""
        service = ProjectCreationService(test_config, mock_github_manager)
        with pytest.raises(ProjectCreationError, match="too long"):
            service._validate_project_id("a" * 101)

    def test_validate_project_id_path_traversal(self, test_config, mock_github_manager):
        """Test that path traversal attempts are blocked."""
        service = ProjectCreationService(test_config, mock_github_manager)
        with pytest.raises(ProjectCreationError, match="path separators"):
            service._validate_project_id("../evil")
        with pytest.raises(ProjectCreationError, match="path separators"):
            service._validate_project_id("foo/bar")
        with pytest.raises(ProjectCreationError, match="path separators"):
            service._validate_project_id("foo\\bar")

    def test_validate_project_id_invalid_chars(self, test_config, mock_github_manager):
        """Test that invalid characters are rejected."""
        service = ProjectCreationService(test_config, mock_github_manager)
        with pytest.raises(ProjectCreationError, match="must start with alphanumeric"):
            service._validate_project_id("-starts-with-dash")
        with pytest.raises(ProjectCreationError, match="must start with alphanumeric"):
            service._validate_project_id("_starts-with-underscore")

    def test_validate_project_id_valid(self, test_config, mock_github_manager):
        """Test that valid project IDs pass validation."""
        service = ProjectCreationService(test_config, mock_github_manager)
        # These should not raise
        service._validate_project_id("my-project")
        service._validate_project_id("my_project")
        service._validate_project_id("MyProject123")
        service._validate_project_id("a")

    @pytest.mark.asyncio
    async def test_create_project_directory_exists(
        self, test_config, mock_github_manager
    ):
        """Test that creating a project fails if directory exists."""
        service = ProjectCreationService(test_config, mock_github_manager)

        # Create the directory first
        (test_config.base_dir / "existing-project").mkdir()

        request = ProjectCreationRequest(
            project_id="existing-project",
            channel_name="existing-project",
        )

        with pytest.raises(ProjectCreationError, match="Directory already exists"):
            await service.create_project(request)

    @pytest.mark.asyncio
    async def test_create_project_already_configured(
        self, test_config, mock_github_manager
    ):
        """Test that creating an already configured project fails."""
        # Add project to config
        test_config.projects["test-project"] = Project(
            id="test-project",
            channel_name="test-project",
            path=test_config.base_dir / "test-project",
            default_agent_id="claude",
        )

        service = ProjectCreationService(test_config, mock_github_manager)
        request = ProjectCreationRequest(
            project_id="test-project",
            channel_name="test-project",
        )

        with pytest.raises(ProjectCreationError, match="already configured"):
            await service.create_project(request)

    @pytest.mark.asyncio
    async def test_create_project_github_not_configured(self, test_config):
        """Test that creating a project fails if GitHub is not configured."""
        mock_github = MagicMock()
        mock_github.is_configured.return_value = False

        service = ProjectCreationService(test_config, mock_github)
        request = ProjectCreationRequest(
            project_id="new-project",
            channel_name="new-project",
        )

        with pytest.raises(ProjectCreationError, match="not configured"):
            await service.create_project(request)

    @pytest.mark.asyncio
    async def test_create_project_success(self, test_config, mock_github_manager):
        """Test successful project creation."""
        service = ProjectCreationService(test_config, mock_github_manager)

        # Mock git commands to succeed
        with patch.object(service, "_run_git", new_callable=AsyncMock) as mock_git:
            mock_git.return_value = ""

            request = ProjectCreationRequest(
                project_id="new-project",
                channel_name="new-project",
                default_agent_id="claude",
                default_base_branch="main",
            )

            project = await service.create_project(request)

            assert project.id == "new-project"
            assert project.channel_name == "new-project"
            assert project.default_agent_id == "claude"
            assert project.github is not None
            assert project.github.owner == "test-user"
            assert project.github.repo == "new-project"
            assert project.github.default_base_branch == "main"

            # Verify local directory was created
            assert (test_config.base_dir / "new-project").exists()
            assert (test_config.base_dir / "new-project" / "README.md").exists()

            # Verify projects.yaml was updated
            import yaml

            projects_yaml = test_config.config_dir / "projects.yaml"
            with open(projects_yaml) as f:
                data = yaml.safe_load(f)

            assert "new-project" in data["projects"]
            assert data["projects"]["new-project"]["default_agent"] == "claude"
            assert data["projects"]["new-project"]["github"]["owner"] == "test-user"

    @pytest.mark.asyncio
    async def test_create_project_cleanup_on_failure(
        self, test_config, mock_github_manager
    ):
        """Test that failed creation cleans up local directory."""
        service = ProjectCreationService(test_config, mock_github_manager)

        # Mock git init to succeed but push to fail
        call_count = 0

        async def mock_git(cwd, args):
            nonlocal call_count
            call_count += 1
            if "push" in args:
                raise ProjectCreationError("Push failed")
            return ""

        with patch.object(service, "_run_git", side_effect=mock_git):
            request = ProjectCreationRequest(
                project_id="failed-project",
                channel_name="failed-project",
            )

            with pytest.raises(ProjectCreationError, match="Push failed"):
                await service.create_project(request)

            # Verify local directory was cleaned up
            assert not (test_config.base_dir / "failed-project").exists()

    def test_update_config(self, test_config, mock_github_manager):
        """Test that update_config updates the internal config reference."""
        service = ProjectCreationService(test_config, mock_github_manager)

        new_config = MagicMock()
        service.update_config(new_config)

        assert service._config is new_config
