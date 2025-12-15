"""Tests for CommandDispatcher."""

import pytest
from src.core.commands.dispatcher import CommandDispatcher
from src.core.commands.parser import ParsedCommand


class TestCommandDispatcher:
    """Tests for CommandDispatcher."""

    @pytest.fixture
    def dispatcher(self):
        return CommandDispatcher()

    def test_get_spec_by_name(self, dispatcher):
        """Lookup command spec by primary name."""
        print("\n INPUT: get_spec('use')")
        spec = dispatcher.get_spec("use")
        print(f" OUTPUT: {spec}")
        assert spec is not None
        assert spec.handler_id == "session.use"

    def test_get_spec_status(self, dispatcher):
        """Lookup status command spec."""
        print("\n INPUT: get_spec('status')")
        spec = dispatcher.get_spec("status")
        print(f" OUTPUT: {spec}")
        assert spec is not None
        assert spec.handler_id == "session.status"

    def test_get_spec_end(self, dispatcher):
        """Lookup end command spec."""
        print("\n INPUT: get_spec('end')")
        spec = dispatcher.get_spec("end")
        print(f" OUTPUT: {spec}")
        assert spec is not None
        assert spec.handler_id == "session.end"

    def test_get_spec_by_alias(self, dispatcher):
        """Lookup command spec by alias."""
        print("\n INPUT: get_spec('commands')")
        spec = dispatcher.get_spec("commands")
        print(f" OUTPUT: {spec}")
        assert spec is not None
        assert spec.name == "help"

    def test_get_spec_case_insensitive(self, dispatcher):
        """Lookup should be case-insensitive."""
        print("\n INPUT: get_spec('HELP')")
        spec = dispatcher.get_spec("HELP")
        print(f" OUTPUT: {spec}")
        assert spec is not None
        assert spec.name == "help"

    def test_get_spec_unknown_returns_none(self, dispatcher):
        """Unknown command returns None."""
        print("\n INPUT: get_spec('unknown')")
        spec = dispatcher.get_spec("unknown")
        print(f" OUTPUT: {spec}")
        assert spec is None

    def test_parse_bot_command_with_mention(self, dispatcher):
        """Parse @remote-coder mention syntax."""
        print("\n INPUT: parse_bot_command('@remote-coder help')")
        result = dispatcher.parse_bot_command("@remote-coder help")
        print(f" OUTPUT: {result}")
        assert result is not None
        assert result.name == "help"
        assert result.args == []

    def test_parse_bot_command_with_args(self, dispatcher):
        """Parse bot command with arguments."""
        print("\n INPUT: parse_bot_command('@remote-coder use claude')")
        result = dispatcher.parse_bot_command("@remote-coder use claude")
        print(f" OUTPUT: {result}")
        assert result is not None
        assert result.name == "use"
        assert result.args == ["claude"]

    def test_parse_bot_command_without_at(self, dispatcher):
        """Parse bot command without @ symbol."""
        print("\n INPUT: parse_bot_command('remote-coder help')")
        result = dispatcher.parse_bot_command("remote-coder help")
        print(f" OUTPUT: {result}")
        assert result is not None
        assert result.name == "help"

    def test_parse_bot_command_not_recognized(self, dispatcher):
        """Non-bot command text returns None."""
        print("\n INPUT: parse_bot_command('hello world')")
        result = dispatcher.parse_bot_command("hello world")
        print(f" OUTPUT: {result}")
        assert result is None

    def test_build_help_lines(self, dispatcher):
        """Build help text for all commands."""
        print("\n INPUT: build_help_lines()")
        lines = dispatcher.build_help_lines()
        print(f" OUTPUT:\n" + "\n".join(lines))
        assert len(lines) > 0
        assert any("!use" in line for line in lines)
        assert any("!help" in line for line in lines)

    def test_all_commands_registered(self, dispatcher):
        """Verify all expected commands are registered."""
        expected = [
            "use",
            "status",
            "end",
            "review",
            "purge",
            "agents",
            "models",
            "reload-projects",
            "stash",
            "help",
        ]
        print(f"\n INPUT: Check all commands registered")
        for cmd in expected:
            spec = dispatcher.get_spec(cmd)
            status = "PASS" if spec else "FAIL"
            print(f"   {cmd}: {status}")
            assert spec is not None, f"Command '{cmd}' not registered"

    def test_specs_property(self, dispatcher):
        """Test that specs property returns all command specs."""
        print("\n INPUT: dispatcher.specs")
        specs = dispatcher.specs
        print(f" OUTPUT: {len(specs)} specs")
        assert len(specs) >= 10  # At least 10 commands
