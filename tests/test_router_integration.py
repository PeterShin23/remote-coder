"""Integration tests for Router command handling."""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import AsyncMock

import pytest

from src.core.config import Config
from src.core.models import Agent, AgentType, Project, WorkingDirMode, GitHubRepoConfig
from src.core.router import Router
from src.core.conversation.session_manager import SessionManager


class StubGitHubManager:
    """Minimal GitHub manager stub for tests."""

    def __init__(self) -> None:
        self.token = None

    def update_token(self, token: str | None) -> None:
        self.token = token

    def is_configured(self) -> bool:
        return False

    async def get_unresolved_comments(self, *args: Any, **kwargs: Any):
        return []

    async def ensure_pull_request(self, *args: Any, **kwargs: Any):
        raise AssertionError("PR publishing should not occur in these tests")


class DummyChatAdapter:
    """Captures Slack messages emitted by the router."""

    def __init__(self) -> None:
        self.messages: list[Dict[str, str]] = []

    async def send_message(self, channel: str, thread_ts: str, text: str) -> None:
        self.messages.append({"channel": channel, "thread_ts": thread_ts, "text": text})


@pytest.fixture
def router_setup(tmp_path):
    session_manager = SessionManager(history_limit=20)
    test_project_path = tmp_path / "repo"
    test_project_path.mkdir()

    project = Project(
        id="test-project",
        channel_name="test-channel",
        path=test_project_path,
        default_agent_id="claude",
        github=GitHubRepoConfig(owner="owner", repo="repo", default_base_branch="main"),
    )
    agent = Agent(
        id="claude",
        type=AgentType.CLAUDE,
        command=["echo"],
        working_dir_mode=WorkingDirMode.PROJECT,
        models={"default": "sonnet", "available": ["sonnet"]},
    )
    config = Config(
        projects={project.channel_name: project, project.id: project},
        agents={agent.id: agent},
        slack_bot_token="x",
        slack_app_token="y",
        slack_allowed_user_ids=["U123"],
        github_token=None,
    )
    github_manager = StubGitHubManager()
    router = Router(session_manager, config, github_manager, config_root=tmp_path)
    router._git_workflow.setup_session_branch = AsyncMock(return_value=None)  # type: ignore[attr-defined]
    router._git_workflow.maybe_publish_code_changes = AsyncMock(return_value=None)  # type: ignore[attr-defined]
    router._agent_runner.run = AsyncMock()  # type: ignore[attr-defined]
    router._maintenance_commands._config_loader = lambda: router._config  # type: ignore[attr-defined]

    adapter = DummyChatAdapter()
    router.bind_adapter(adapter)
    return router, adapter


@pytest.mark.asyncio
async def test_help_command_lists_commands(router_setup):
    router, adapter = router_setup

    event = {
        "channel": "C123",
        "channel_name": "test-channel",
        "text": "!help",
        "ts": "111.222",
    }

    await router.handle_message(event)

    assert any("Available commands" in msg["text"] for msg in adapter.messages)


@pytest.mark.asyncio
async def test_status_command_flow(router_setup):
    router, adapter = router_setup

    create_event = {
        "channel": "C123",
        "channel_name": "test-channel",
        "text": "hello",
        "ts": "333.444",
    }
    await router.handle_message(create_event)

    status_event = {
        "channel": "C123",
        "channel_name": "test-channel",
        "text": "!status",
        "thread_ts": "333.444",
    }
    await router.handle_message(status_event)

    assert any("Session ID" in msg["text"] for msg in adapter.messages)


@pytest.mark.asyncio
async def test_unknown_command(router_setup):
    router, adapter = router_setup

    event = {
        "channel": "C123",
        "channel_name": "test-channel",
        "text": "!doesnotexist",
        "ts": "555.666",
    }

    await router.handle_message(event)

    assert any("Unknown command" in msg["text"] for msg in adapter.messages)
