"""Tests for CatalogCommandHandler."""

from __future__ import annotations

import pytest

from src.core.commands.catalog import CatalogCommandHandler
from src.core.commands.dispatcher import CommandDispatcher
from src.core.commands.parser import ParsedCommand


class TestCatalogCommands:
    """Catalog command handler tests."""

    @pytest.fixture
    def handler(self, test_config, mock_send_message):
        dispatcher = CommandDispatcher()
        return CatalogCommandHandler(
            config=test_config,
            dispatcher=dispatcher,
            send_message=mock_send_message,
        )

    @pytest.mark.asyncio
    async def test_handle_agents_lists_all(self, handler, command_context, mock_send_message):
        command = ParsedCommand(name="agents", args=[])

        await handler.handle_agents(command, command_context)

        output = mock_send_message.messages[-1]["text"]
        assert "Available agents" in output
        assert "`claude`" in output or "`codex`" in output

    @pytest.mark.asyncio
    async def test_handle_models_lists_models(self, handler, command_context, mock_send_message):
        command = ParsedCommand(name="models", args=[])

        await handler.handle_models(command, command_context)

        output = mock_send_message.messages[-1]["text"]
        assert "Available models" in output
        assert "sonnet" in output

    @pytest.mark.asyncio
    async def test_handle_help_uses_dispatcher(self, handler, command_context, mock_send_message):
        command = ParsedCommand(name="help", args=[])

        await handler.handle_help(command, command_context)

        output = mock_send_message.messages[-1]["text"]
        assert "Available commands" in output
        assert "!use" in output
