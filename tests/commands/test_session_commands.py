"""Tests for SessionCommandHandler."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.core.commands.parser import ParsedCommand
from src.core.commands.session import SessionCommandHandler
from src.core.errors import AgentNotFound
from src.core.models import SessionStatus


class TestSessionCommands:
    """Session command handler test suite."""

    @pytest.fixture
    def handler(self, session_manager, test_config, mock_send_message):
        return SessionCommandHandler(
            session_manager=session_manager,
            config=test_config,
            send_message=mock_send_message,
        )

    @pytest.mark.asyncio
    async def test_handle_use_switch_agent(self, handler, command_context, session_manager, mock_send_message):
        command = ParsedCommand(name="use", args=["codex"])

        await handler.handle_use(command, command_context)

        stored = session_manager.get_session(command_context.session.id)
        assert stored.active_agent_id == "codex"
        assert "Switched to `codex`" in mock_send_message.messages[-1]["text"]

    @pytest.mark.asyncio
    async def test_handle_use_switch_agent_and_model(self, handler, command_context, session_manager, mock_send_message):
        command = ParsedCommand(name="use", args=["claude", "opus"])

        await handler.handle_use(command, command_context)

        stored = session_manager.get_session(command_context.session.id)
        assert stored.active_agent_id == "claude"
        assert stored.active_model == "opus"
        assert "`opus`" in mock_send_message.messages[-1]["text"]

    @pytest.mark.asyncio
    async def test_handle_use_unknown_agent(self, handler, command_context, test_config, mock_send_message):
        test_config.get_agent = MagicMock(side_effect=AgentNotFound("unknown"))
        command = ParsedCommand(name="use", args=["unknown"])

        await handler.handle_use(command, command_context)

        assert "Unknown agent" in mock_send_message.messages[-1]["text"]

    @pytest.mark.asyncio
    async def test_handle_use_invalid_model(self, handler, command_context, mock_send_message):
        command = ParsedCommand(name="use", args=["claude", "nonexistent"])

        await handler.handle_use(command, command_context)

        assert "Unknown model" in mock_send_message.messages[-1]["text"]

    @pytest.mark.asyncio
    async def test_handle_use_missing_args(self, handler, command_context, mock_send_message):
        command = ParsedCommand(name="use", args=[])

        await handler.handle_use(command, command_context)

        assert "Usage: `!use <agent> [model]`" in mock_send_message.messages[-1]["text"]

    @pytest.mark.asyncio
    async def test_handle_status_lists_details(self, handler, command_context, mock_send_message):
        command = ParsedCommand(name="status", args=[])

        await handler.handle_status(command, command_context)

        output = mock_send_message.messages[-1]["text"]
        assert "Session ID" in output
        assert command_context.session.active_agent_id in output

    @pytest.mark.asyncio
    async def test_handle_end_active_session(self, handler, command_context, session_manager, mock_send_message):
        command = ParsedCommand(name="end", args=[])

        await handler.handle_end(command, command_context)

        updated = session_manager.get_session(command_context.session.id)
        assert updated.status == SessionStatus.ENDED
        assert "Session ended" in mock_send_message.messages[-1]["text"]

    @pytest.mark.asyncio
    async def test_handle_end_already_ended(self, handler, command_context, mock_send_message):
        command_context.session.status = SessionStatus.ENDED
        command = ParsedCommand(name="end", args=[])
        await handler.handle_end(command, command_context)

        assert "Session already ended" in mock_send_message.messages[-1]["text"]
