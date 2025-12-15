"""Shared fixtures for command handler tests."""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.core.models import Project, Agent, AgentType, GitHubRepoConfig, WorkingDirMode
from src.core.conversation import SessionManager
from src.core.config import Config
from src.core.commands.context import CommandContext


@pytest.fixture
def mock_send_message():
    """Async mock for send_message that prints to terminal."""

    messages: list[dict[str, str]] = []

    async def _send(channel: str, thread_ts: str, text: str):
        print(f"\n{'='*60}")
        print("SLACK OUTPUT")
        print(f"   Channel: {channel}")
        print(f"   Thread:  {thread_ts}")
        print(f"{'-'*60}")
        print(f"{text}")
        print(f"{'='*60}\n")
        messages.append({"channel": channel, "thread_ts": thread_ts, "text": text})

    _send.messages = messages  # type: ignore[attr-defined]
    return _send


@pytest.fixture
def test_project(tmp_path):
    """Create a test project with GitHub config."""
    return Project(
        id="test-project",
        channel_name="test-channel",
        path=tmp_path,
        default_agent_id="claude",
        github=GitHubRepoConfig(
            owner="test-owner",
            repo="test-repo",
            default_base_branch="main",
        ),
    )


@pytest.fixture
def test_config():
    """Create a real Config with agents suitable for tests."""
    agents = {
        "claude": Agent(
            id="claude",
            type=AgentType.CLAUDE,
            command=["claude"],
            working_dir_mode=WorkingDirMode.PROJECT,
            models={"default": "sonnet", "available": ["sonnet", "opus", "haiku"]},
        ),
        "codex": Agent(
            id="codex",
            type=AgentType.CODEX,
            command=["codex"],
            working_dir_mode=WorkingDirMode.PROJECT,
            models={"default": "base", "available": ["base", "mini"]},
        ),
    }

    config = Config(
        projects={},
        agents=agents,
        slack_bot_token="bot-token",
        slack_app_token="app-token",
        slack_allowed_user_ids=["U123"],
        github_token=None,
    )
    return config


@pytest.fixture
def session_manager(tmp_path):
    """Create a real SessionManager for tests."""
    return SessionManager(history_limit=20)


@pytest.fixture
def command_context(session_manager: SessionManager, test_project: Project):
    """Create CommandContext backed by a SessionManager session."""
    session = session_manager.create_session(
        project=test_project,
        channel_id="C123456",
        thread_ts="1234567890.123456",
        agent_id=test_project.default_agent_id,
        agent_type=AgentType.CLAUDE,
    )
    session.active_model = "sonnet"
    return CommandContext(
        session=session,
        project=test_project,
        channel=session.channel_id,
        thread_ts=session.thread_ts,
    )
