"""Tests for Router project creation flow with Y/N text responses."""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.config import Config
from src.core.models import Agent, AgentType, GitHubRepoConfig, Project, WorkingDirMode
from src.core.commands.project_creation import PendingProjectCreation
from src.core.router import Router
from src.core.conversation.session_manager import SessionManager


class StubGitHubManager:
    """Minimal GitHub manager stub for tests."""

    def __init__(self) -> None:
        self.token = None
        self._client = MagicMock()

    def update_token(self, token: str | None) -> None:
        self.token = token

    def is_configured(self) -> bool:
        return True

    async def get_unresolved_comments(self, *args: Any, **kwargs: Any):
        return []

    async def ensure_pull_request(self, *args: Any, **kwargs: Any):
        raise AssertionError("PR publishing should not occur in these tests")


class DummyChatAdapter:
    """Captures Slack messages emitted by the router."""

    def __init__(self) -> None:
        self.messages: list[Dict[str, str]] = []
        self._msg_counter = 0

    async def send_message(
        self, channel: str, thread_ts: str, text: str
    ) -> Optional[str]:
        self._msg_counter += 1
        msg_ts = f"{thread_ts}.{self._msg_counter}"
        self.messages.append(
            {"channel": channel, "thread_ts": thread_ts, "text": text, "ts": msg_ts}
        )
        return msg_ts


@pytest.fixture
def router_setup(tmp_path):
    """Set up a router for testing with no projects configured."""
    session_manager = SessionManager(history_limit=20)
    base_dir = tmp_path / "projects"
    base_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Create projects.yaml
    projects_yaml = config_dir / "projects.yaml"
    projects_yaml.write_text(f'base_dir: "{base_dir}"\nprojects: {{}}\n')

    # Create agents.yaml (needed for config reload)
    agents_yaml = config_dir / "agents.yaml"
    agents_yaml.write_text("""agents:
  claude:
    type: claude
    command: ["echo"]
    working_dir_mode: project
    models:
      default: sonnet
      available: ["sonnet"]
""")

    # Create .env file (needed for config reload)
    env_file = config_dir / ".env"
    env_file.write_text("""SLACK_BOT_TOKEN=x
SLACK_APP_TOKEN=y
SLACK_ALLOWED_USER_IDS=U123
GITHUB_TOKEN=test-token
""")

    agent = Agent(
        id="claude",
        type=AgentType.CLAUDE,
        command=["echo"],
        working_dir_mode=WorkingDirMode.PROJECT,
        models={"default": "sonnet", "available": ["sonnet"]},
    )
    config = Config(
        projects={},  # No projects configured
        agents={agent.id: agent},
        slack_bot_token="x",
        slack_app_token="y",
        slack_allowed_user_ids=["U123"],
        base_dir=base_dir,
        config_dir=config_dir,
        github_token="test-token",
    )
    github_manager = StubGitHubManager()
    router = Router(session_manager, config, github_manager, config_root=config_dir)
    router._git_workflow.setup_session_branch = AsyncMock(return_value=None)
    router._git_workflow.maybe_publish_code_changes = AsyncMock(return_value=None)
    router._agent_runner.run = AsyncMock()

    adapter = DummyChatAdapter()
    router.bind_adapter(adapter)
    return router, adapter, tmp_path


class TestPendingProjectCreation:
    """Tests for PendingProjectCreation dataclass."""

    def test_pending_project_creation_fields(self):
        """Test PendingProjectCreation has expected fields."""
        pending = PendingProjectCreation(
            channel_id="C123",
            channel_name="my-project",
            thread_ts="111.000",
            created_at=1234567890.0,
        )
        assert pending.channel_id == "C123"
        assert pending.channel_name == "my-project"
        assert pending.thread_ts == "111.000"
        assert pending.created_at == 1234567890.0
        assert pending.state == "awaiting_confirmation"
        assert pending.selected_agent_id is None
        assert pending.agent_options == []
        assert pending.model_options == []


class TestRouterMissingProject:
    """Tests for handling messages to channels without projects."""

    @pytest.mark.asyncio
    async def test_missing_project_sends_prompt(self, router_setup):
        """Test that message to unknown channel sends creation prompt."""
        router, adapter, _ = router_setup

        event = {
            "channel": "C123",
            "channel_name": "new-idea",
            "text": "Hello",
            "ts": "111.222",
        }

        await router.handle_message(event)

        # Should have sent the prompt message
        assert len(adapter.messages) == 1
        assert "new-idea" in adapter.messages[0]["text"]
        assert "Reply with \"Y\"" in adapter.messages[0]["text"]

    @pytest.mark.asyncio
    async def test_missing_project_tracks_pending(self, router_setup):
        """Test that pending project creation is tracked."""
        router, adapter, _ = router_setup

        event = {
            "channel": "C123",
            "channel_name": "new-idea",
            "text": "Hello",
            "ts": "111.222",
        }

        await router.handle_message(event)

        # Should be tracking the pending creation by channel_id
        handler = router._project_creation_handler
        assert "C123" in handler._pending_projects
        pending = handler._pending_projects["C123"]
        assert pending.channel_id == "C123"
        assert pending.channel_name == "new-idea"


class TestRouterYesNoHandling:
    """Tests for Y/N response handling in Router."""

    @pytest.mark.asyncio
    async def test_full_creation_flow(self, router_setup):
        """Test full flow: Y → pick agent → pick model → project created."""
        router, adapter, tmp_path = router_setup

        # Step 1: Send message to trigger prompt
        event1 = {
            "channel": "C123",
            "channel_name": "new-idea",
            "text": "Hello",
            "ts": "111.222",
        }
        await router.handle_message(event1)

        # Step 2: Send 'Y' - should show agent options (thread_ts points to original)
        event2 = {
            "channel": "C123",
            "channel_name": "new-idea",
            "text": "Y",
            "ts": "111.333",
            "thread_ts": "111.222",
        }
        await router.handle_message(event2)
        assert any("Which agent" in msg["text"] for msg in adapter.messages)
        assert any("1. claude" in msg["text"] for msg in adapter.messages)

        # Step 3: Pick agent - should show model options
        event3 = {
            "channel": "C123",
            "channel_name": "new-idea",
            "text": "1",
            "ts": "111.444",
            "thread_ts": "111.222",
        }
        await router.handle_message(event3)
        assert any("Which model" in msg["text"] for msg in adapter.messages)

        # Step 4: Pick model - should create project
        # Write the project to projects.yaml so load_config finds it
        config_dir = tmp_path / "config"
        projects_yaml = config_dir / "projects.yaml"
        project_dir = tmp_path / "projects" / "new-idea"
        project_dir.mkdir(parents=True, exist_ok=True)
        projects_yaml.write_text(f"""base_dir: "{tmp_path / 'projects'}"
projects:
  new-idea:
    path: new-idea
    default_agent: claude
    default_model: sonnet
    github:
      owner: test-user
      repo: new-idea
      default_base_branch: main
""")

        with patch.object(
            router._project_creation_handler._project_creator, "create_project", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = Project(
                id="new-idea",
                channel_name="new-idea",
                path=project_dir,
                default_agent_id="claude",
                default_model="sonnet",
                github=GitHubRepoConfig(
                    owner="test-user",
                    repo="new-idea",
                    default_base_branch="main",
                ),
            )

            event4 = {
                "channel": "C123",
                "channel_name": "new-idea",
                "text": "1",
                "ts": "111.555",
                "thread_ts": "111.222",
            }
            await router.handle_message(event4)

            mock_create.assert_called_once()

        assert any("Setting up project" in msg["text"] for msg in adapter.messages)
        assert any("I've set up" in msg["text"] for msg in adapter.messages)
        assert "C123" not in router._project_creation_handler._pending_projects

        # Session should be automatically created after project setup
        session = router._session_manager.get_by_thread("C123", "111.222")
        assert session is not None
        assert session.active_agent_id == "claude"
        assert session.active_model == "sonnet"

        # "Starting session" message should be sent after project setup
        assert any("Starting session for" in msg["text"] for msg in adapter.messages)
        starting_msg = next(m for m in adapter.messages if "Starting session for" in m["text"])
        assert "new-idea" in starting_msg["text"]
        assert "claude" in starting_msg["text"]
        assert "sonnet" in starting_msg["text"]

    @pytest.mark.asyncio
    async def test_yes_shows_agent_options(self, router_setup):
        """Test that 'Y' response shows agent options."""
        router, adapter, _ = router_setup

        event1 = {
            "channel": "C123",
            "channel_name": "new-idea",
            "text": "Hello",
            "ts": "111.222",
        }
        await router.handle_message(event1)

        event2 = {
            "channel": "C123",
            "channel_name": "new-idea",
            "text": "y",
            "ts": "111.333",
        }
        await router.handle_message(event2)

        assert any("Which agent" in msg["text"] for msg in adapter.messages)
        handler = router._project_creation_handler
        assert "C123" in handler._pending_projects
        assert handler._pending_projects["C123"].state == "awaiting_agent"

    @pytest.mark.asyncio
    async def test_yes_full_word_works(self, router_setup):
        """Test that 'yes' also works."""
        router, adapter, _ = router_setup

        event1 = {
            "channel": "C123",
            "channel_name": "new-idea",
            "text": "Hello",
            "ts": "111.222",
        }
        await router.handle_message(event1)

        event2 = {
            "channel": "C123",
            "channel_name": "new-idea",
            "text": "yes",
            "ts": "111.333",
        }
        await router.handle_message(event2)

        assert any("Which agent" in msg["text"] for msg in adapter.messages)

    @pytest.mark.asyncio
    async def test_no_response_rejects(self, router_setup):
        """Test that 'N' response sends rejection message."""
        router, adapter, _ = router_setup

        # Trigger the prompt
        event1 = {
            "channel": "C123",
            "channel_name": "new-idea",
            "text": "Hello",
            "ts": "111.222",
        }
        await router.handle_message(event1)

        # Send 'N' response
        event2 = {
            "channel": "C123",
            "channel_name": "new-idea",
            "text": "N",
            "ts": "111.333",
        }
        await router.handle_message(event2)

        # Should have sent rejection message
        assert any("rename the channel" in msg["text"] for msg in adapter.messages)

        # Pending should be cleaned up
        assert "C123" not in router._project_creation_handler._pending_projects

    @pytest.mark.asyncio
    async def test_no_lowercase_works(self, router_setup):
        """Test that lowercase 'n' also works."""
        router, adapter, _ = router_setup

        event1 = {
            "channel": "C123",
            "channel_name": "new-idea",
            "text": "Hello",
            "ts": "111.222",
        }
        await router.handle_message(event1)

        event2 = {
            "channel": "C123",
            "channel_name": "new-idea",
            "text": "n",
            "ts": "111.333",
        }
        await router.handle_message(event2)

        assert any("rename the channel" in msg["text"] for msg in adapter.messages)
        assert "C123" not in router._project_creation_handler._pending_projects

    @pytest.mark.asyncio
    async def test_invalid_response_reminds_user(self, router_setup):
        """Test that invalid responses remind user to use Y/N."""
        router, adapter, _ = router_setup

        # Trigger the prompt
        event1 = {
            "channel": "C123",
            "channel_name": "new-idea",
            "text": "Hello",
            "ts": "111.222",
        }
        await router.handle_message(event1)

        # Send invalid response
        event2 = {
            "channel": "C123",
            "channel_name": "new-idea",
            "text": "maybe",
            "ts": "111.333",
        }
        await router.handle_message(event2)

        # Should have sent reminder message
        assert any("Please reply with \"Y\"" in msg["text"] for msg in adapter.messages)

        # Pending should still be tracked
        assert "C123" in router._project_creation_handler._pending_projects

    @pytest.mark.asyncio
    async def test_creation_failure_sends_error(self, router_setup):
        """Test that failed project creation sends error message."""
        router, adapter, _ = router_setup

        # Step 1: Trigger the prompt
        event1 = {
            "channel": "C123",
            "channel_name": "new-idea",
            "text": "Hello",
            "ts": "111.222",
        }
        await router.handle_message(event1)

        # Step 2: Say Y - shows agent options
        event2 = {
            "channel": "C123",
            "channel_name": "new-idea",
            "text": "Y",
            "ts": "111.333",
        }
        await router.handle_message(event2)

        # Step 3: Pick agent - shows model options
        event3 = {
            "channel": "C123",
            "channel_name": "new-idea",
            "text": "1",
            "ts": "111.444",
        }
        await router.handle_message(event3)

        # Step 4: Pick model - creation fails
        with patch.object(
            router._project_creation_handler._project_creator, "create_project", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = Exception("GitHub API error")

            event4 = {
                "channel": "C123",
                "channel_name": "new-idea",
                "text": "1",
                "ts": "111.555",
            }
            await router.handle_message(event4)

        # Should have sent error message
        assert any("couldn't create the project" in msg["text"] for msg in adapter.messages)

        # Pending should be cleaned up even on failure
        assert "C123" not in router._project_creation_handler._pending_projects


class TestProjectCreationHandler:
    """Tests for ProjectCreationHandler directly."""

    def test_pending_project_tracking(self, router_setup):
        """Test that pending projects are tracked correctly."""
        router, _, _ = router_setup
        handler = router._project_creation_handler

        # No pending projects initially
        assert "C123" not in handler._pending_projects

        # Manually add a pending project
        handler._pending_projects["C123"] = PendingProjectCreation(
            channel_id="C123",
            channel_name="test",
            thread_ts="111.000",
            created_at=12345.0,
        )

        assert "C123" in handler._pending_projects
        assert "C456" not in handler._pending_projects

    def test_pending_project_fields(self, router_setup):
        """Test PendingProjectCreation fields."""
        router, _, _ = router_setup
        handler = router._project_creation_handler

        handler._pending_projects["C123"] = PendingProjectCreation(
            channel_id="C123",
            channel_name="my-project",
            thread_ts="111.000",
            created_at=12345.0,
        )

        pending = handler._pending_projects["C123"]
        assert pending.channel_id == "C123"
        assert pending.channel_name == "my-project"
        assert pending.thread_ts == "111.000"
        assert pending.created_at == 12345.0
