"""Tests for MaintenanceCommandHandler."""

from __future__ import annotations

import subprocess
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.commands.maintenance import MaintenanceCommandHandler
from src.core.commands.parser import ParsedCommand
from src.core.errors import GitHubError, ConfigError


class TestMaintenanceCommands:
    """Maintenance command handler tests."""

    @pytest.fixture
    def git_ops(self):
        return {
            "repo_has_changes": AsyncMock(return_value=True),
            "stash_changes": AsyncMock(return_value=True),
            "setup_session_branch": AsyncMock(),
        }

    @pytest.fixture
    def handler(self, session_manager, test_config, mock_send_message, git_ops):
        apply_mock = MagicMock()
        loader_mock = MagicMock(return_value=test_config)
        handler = MaintenanceCommandHandler(
            session_manager=session_manager,
            config_loader=loader_mock,
            apply_new_config=apply_mock,
            get_current_config=lambda: test_config,
            active_runs={},
            repo_has_changes=git_ops["repo_has_changes"],
            stash_changes=git_ops["stash_changes"],
            setup_session_branch=git_ops["setup_session_branch"],
            send_message=mock_send_message,
        )
        handler._config_loader_mock = loader_mock  # type: ignore[attr-defined]
        handler._apply_mock = apply_mock  # type: ignore[attr-defined]
        return handler

    @pytest.mark.asyncio
    async def test_handle_reload_projects_success(self, handler, command_context, mock_send_message):
        command = ParsedCommand(name="reload-projects", args=[])

        await handler.handle_reload_projects(command, command_context)

        handler._apply_mock.assert_called_once()  # type: ignore[attr-defined]
        assert "Reloaded configuration" in mock_send_message.messages[-1]["text"]

    @pytest.mark.asyncio
    async def test_handle_reload_projects_config_error(self, handler, command_context, mock_send_message):
        handler._config_loader_mock.side_effect = ConfigError("boom")  # type: ignore[attr-defined]
        command = ParsedCommand(name="reload-projects", args=[])

        await handler.handle_reload_projects(command, command_context)

        assert "Failed to reload config" in mock_send_message.messages[-1]["text"]

    @pytest.mark.asyncio
    async def test_handle_purge_with_active_runs(self, handler, command_context, session_manager, mock_send_message):
        session_manager.create_session(
            project=command_context.project,
            channel_id=command_context.channel,
            thread_ts=command_context.thread_ts,
            agent_id="claude",
            agent_type=command_context.session.active_agent_type,
        )

        task = asyncio.create_task(asyncio.sleep(1))
        handler._active_runs["run1"] = {"task": task}  # type: ignore[attr-defined]
        command = ParsedCommand(name="purge", args=[])

        await handler.handle_purge(command, command_context)

        assert "Remote Coder is now in a clean state" in mock_send_message.messages[-1]["text"]

    @pytest.mark.asyncio
    async def test_handle_purge_no_sessions(self, handler, command_context, mock_send_message):
        command = ParsedCommand(name="purge", args=[])

        await handler.handle_purge(command, command_context)

        assert "clean state" in mock_send_message.messages[-1]["text"]

    @pytest.mark.asyncio
    async def test_handle_stash_with_changes(self, handler, command_context, git_ops, mock_send_message):
        command = ParsedCommand(name="stash", args=[])

        await handler.handle_stash(command, command_context)

        git_ops["stash_changes"].assert_awaited_once()
        git_ops["setup_session_branch"].assert_awaited_once()
        assert "Session branch ready" in mock_send_message.messages[-1]["text"]

    @pytest.mark.asyncio
    async def test_handle_stash_no_changes(self, handler, command_context, git_ops, mock_send_message):
        git_ops["repo_has_changes"].return_value = False
        command = ParsedCommand(name="stash", args=[])

        await handler.handle_stash(command, command_context)

        assert "No local changes" in mock_send_message.messages[-1]["text"]

    @pytest.mark.asyncio
    async def test_handle_stash_git_error(self, handler, command_context, git_ops, mock_send_message):
        git_ops["stash_changes"].side_effect = subprocess.CalledProcessError(1, "git")
        command = ParsedCommand(name="stash", args=[])

        await handler.handle_stash(command, command_context)

        assert "Failed to stash changes" in mock_send_message.messages[-1]["text"]
