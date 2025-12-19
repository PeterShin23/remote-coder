"""Tests for ProjectCreationService."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.config import Config
from src.core.errors import (
    GitHubError,
    LocalDirNotGitRepoError,
    ProjectCreationError,
    ProjectNotFound,
    RepoExistsError,
)
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


class TestSanitizeRepoName:
    """Tests for _sanitize_repo_name method."""

    def test_sanitize_keeps_letters_numbers_dashes(self, test_config, mock_github_manager):
        """Test that letters, numbers, and dashes are preserved."""
        service = ProjectCreationService(test_config, mock_github_manager)
        assert service._sanitize_repo_name("my-project-123") == "my-project-123"

    def test_sanitize_removes_underscores(self, test_config, mock_github_manager):
        """Test that underscores are removed."""
        service = ProjectCreationService(test_config, mock_github_manager)
        assert service._sanitize_repo_name("my_project") == "myproject"

    def test_sanitize_removes_special_chars(self, test_config, mock_github_manager):
        """Test that special characters are removed."""
        service = ProjectCreationService(test_config, mock_github_manager)
        assert service._sanitize_repo_name("my.project!@#$%") == "myproject"

    def test_sanitize_strips_leading_trailing_dashes(self, test_config, mock_github_manager):
        """Test that leading/trailing dashes are stripped."""
        service = ProjectCreationService(test_config, mock_github_manager)
        assert service._sanitize_repo_name("-my-project-") == "my-project"
        assert service._sanitize_repo_name("---test---") == "test"

    def test_sanitize_empty_result_raises(self, test_config, mock_github_manager):
        """Test that empty result after sanitization raises error."""
        service = ProjectCreationService(test_config, mock_github_manager)
        with pytest.raises(ProjectCreationError, match="empty repo name"):
            service._sanitize_repo_name("___")
        with pytest.raises(ProjectCreationError, match="empty repo name"):
            service._sanitize_repo_name("---")
        with pytest.raises(ProjectCreationError, match="empty repo name"):
            service._sanitize_repo_name("!@#$%")


class TestExistingDirectoryHandling:
    """Tests for handling existing directories."""

    @pytest.mark.asyncio
    async def test_existing_git_repo_adds_to_config(
        self, test_config, mock_github_manager
    ):
        """Test that existing git repo is just added to config."""
        service = ProjectCreationService(test_config, mock_github_manager)

        # Create existing git repo
        repo_path = test_config.base_dir / "existing-repo"
        repo_path.mkdir()
        (repo_path / ".git").mkdir()

        # Mock _run_git to simulate remote URL fetch
        async def mock_git(cwd, args):
            if "get-url" in args:
                return "git@github.com:existing-owner/existing-repo.git"
            return ""

        with patch.object(service, "_run_git", side_effect=mock_git):
            request = ProjectCreationRequest(
                project_id="existing-repo",
                channel_name="existing-repo",
            )

            project = await service.create_project(request)

            assert project.id == "existing-repo"
            assert project.github.owner == "existing-owner"

    @pytest.mark.asyncio
    async def test_existing_dir_not_git_repo_raises(
        self, test_config, mock_github_manager
    ):
        """Test that existing non-git directory raises LocalDirNotGitRepoError."""
        service = ProjectCreationService(test_config, mock_github_manager)

        # Create existing directory without .git
        (test_config.base_dir / "not-a-repo").mkdir()

        request = ProjectCreationRequest(
            project_id="not-a-repo",
            channel_name="not-a-repo",
        )

        with pytest.raises(LocalDirNotGitRepoError, match="isn't a git repository"):
            await service.create_project(request)


class TestGitHubRepoCreation:
    """Tests for GitHub repository creation."""

    @pytest.mark.asyncio
    async def test_github_repo_exists_raises_repo_exists_error(
        self, test_config, mock_github_manager
    ):
        """Test that 'repo exists' error raises RepoExistsError."""
        service = ProjectCreationService(test_config, mock_github_manager)

        # Make create_repo raise "already exists" error
        mock_github_manager._client.get_user().create_repo.side_effect = Exception(
            "Repository 'test' already exists on this account"
        )

        # Mock git commands to succeed
        with patch.object(service, "_run_git", new_callable=AsyncMock) as mock_git:
            mock_git.return_value = ""

            request = ProjectCreationRequest(
                project_id="test-project",
                channel_name="test-project",
            )

            with pytest.raises(RepoExistsError, match="already exists"):
                await service.create_project(request)

    @pytest.mark.asyncio
    async def test_github_other_error_raises_project_creation_error(
        self, test_config, mock_github_manager
    ):
        """Test that other GitHub errors raise ProjectCreationError."""
        service = ProjectCreationService(test_config, mock_github_manager)

        # Make create_repo raise a different error
        mock_github_manager._client.get_user().create_repo.side_effect = Exception(
            "Rate limit exceeded"
        )

        # Mock git commands to succeed
        with patch.object(service, "_run_git", new_callable=AsyncMock) as mock_git:
            mock_git.return_value = ""

            request = ProjectCreationRequest(
                project_id="test-project",
                channel_name="test-project",
            )

            with pytest.raises(ProjectCreationError, match="Something unexpected"):
                await service.create_project(request)


class TestProjectCreationService:
    """Tests for ProjectCreationService."""

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

        with pytest.raises(GitHubError, match="not configured"):
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
    async def test_create_project_sanitizes_channel_name(
        self, test_config, mock_github_manager
    ):
        """Test that channel name with special chars is sanitized."""
        service = ProjectCreationService(test_config, mock_github_manager)

        # Update mock to return correct repo name
        mock_github_manager._client.get_user().create_repo.return_value.full_name = (
            "test-user/my-project"
        )

        # Mock git commands to succeed
        with patch.object(service, "_run_git", new_callable=AsyncMock) as mock_git:
            mock_git.return_value = ""

            request = ProjectCreationRequest(
                project_id="my_project!@#",  # Has special chars
                channel_name="my_project!@#",
                default_agent_id="claude",
                default_base_branch="main",
            )

            project = await service.create_project(request)

            # Should be sanitized to "myproject"
            assert project.id == "myproject"
            assert (test_config.base_dir / "myproject").exists()

    @pytest.mark.asyncio
    async def test_create_project_cleanup_on_failure(
        self, test_config, mock_github_manager
    ):
        """Test that failed creation cleans up local directory and GitHub repo."""
        service = ProjectCreationService(test_config, mock_github_manager)

        # Update mock to return correct repo name for this test
        mock_created_repo = MagicMock()
        mock_created_repo.full_name = "test-user/failed-project"
        mock_github_manager._client.get_user().create_repo.return_value = mock_created_repo

        # Set up mock for repo deletion
        mock_repo_to_delete = MagicMock()
        mock_github_manager._client.get_repo.return_value = mock_repo_to_delete

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

            # Verify GitHub repo deletion was attempted
            mock_github_manager._client.get_repo.assert_called_with("test-user/failed-project")
            mock_repo_to_delete.delete.assert_called_once()

    def test_update_config(self, test_config, mock_github_manager):
        """Test that update_config updates the internal config reference."""
        service = ProjectCreationService(test_config, mock_github_manager)

        new_config = MagicMock()
        service.update_config(new_config)

        assert service._config is new_config

    def test_get_authenticated_remote_url_with_token(self, test_config, mock_github_manager):
        """Test that authenticated URL uses HTTPS with token."""
        service = ProjectCreationService(test_config, mock_github_manager)

        url = service._get_authenticated_remote_url("owner/repo")

        assert url == "https://x-access-token:test-token@github.com/owner/repo.git"

    def test_get_authenticated_remote_url_without_token(self, mock_github_manager):
        """Test that without token, falls back to SSH."""
        config = Config(
            projects={},
            agents={},
            slack_bot_token="bot",
            slack_app_token="app",
            slack_allowed_user_ids=["U123"],
            base_dir=Path("/tmp"),
            config_dir=Path("/tmp"),
            github_token=None,  # No token
        )
        service = ProjectCreationService(config, mock_github_manager)

        url = service._get_authenticated_remote_url("owner/repo")

        assert url == "git@github.com:owner/repo.git"
