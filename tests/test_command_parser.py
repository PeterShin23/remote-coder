"""Tests for command parser."""

import pytest
from src.core.commands.parser import parse_command, ParsedCommand


class TestCommandParser:
    """Tests for parse_command function."""

    def test_parse_basic_command(self):
        """Parse simple command with no args."""
        print("\n INPUT: '!help'")
        result = parse_command("!help")
        print(f" OUTPUT: {result}")
        assert result == ParsedCommand(name="help", args=[])

    def test_parse_command_with_args(self):
        """Parse command with arguments."""
        print("\n INPUT: '!use claude sonnet'")
        result = parse_command("!use claude sonnet")
        print(f" OUTPUT: {result}")
        assert result == ParsedCommand(name="use", args=["claude", "sonnet"])

    def test_parse_command_with_single_arg(self):
        """Parse command with single argument."""
        print("\n INPUT: '!use codex'")
        result = parse_command("!use codex")
        print(f" OUTPUT: {result}")
        assert result == ParsedCommand(name="use", args=["codex"])

    def test_parse_command_case_insensitive(self):
        """Command names should be lowercased."""
        print("\n INPUT: '!HELP'")
        result = parse_command("!HELP")
        print(f" OUTPUT: {result}")
        assert result is not None
        assert result.name == "help"

    def test_parse_command_mixed_case(self):
        """Mixed case command names should be lowercased."""
        print("\n INPUT: '!HeLp'")
        result = parse_command("!HeLp")
        print(f" OUTPUT: {result}")
        assert result is not None
        assert result.name == "help"

    def test_parse_non_command_returns_none(self):
        """Non-command text returns None."""
        print("\n INPUT: 'hello world'")
        result = parse_command("hello world")
        print(f" OUTPUT: {result}")
        assert result is None

    def test_parse_empty_string(self):
        """Empty string returns None."""
        print("\n INPUT: ''")
        result = parse_command("")
        print(f" OUTPUT: {result}")
        assert result is None

    def test_parse_whitespace_only(self):
        """Whitespace only returns None."""
        print("\n INPUT: '   '")
        result = parse_command("   ")
        print(f" OUTPUT: {result}")
        assert result is None

    def test_parse_exclamation_only(self):
        """Exclamation mark only returns None."""
        print("\n INPUT: '!'")
        result = parse_command("!")
        print(f" OUTPUT: {result}")
        assert result is None

    def test_parse_with_leading_whitespace(self):
        """Command with leading whitespace."""
        print("\n INPUT: '  !help'")
        result = parse_command("  !help")
        print(f" OUTPUT: {result}")
        assert result == ParsedCommand(name="help", args=[])

    def test_parse_with_trailing_whitespace(self):
        """Command with trailing whitespace."""
        print("\n INPUT: '!help  '")
        result = parse_command("!help  ")
        print(f" OUTPUT: {result}")
        assert result == ParsedCommand(name="help", args=[])

    def test_parse_with_mention_prefix(self):
        """Command with Slack mention prefix."""
        print("\n INPUT: '<@U123ABC> !help'")
        result = parse_command("<@U123ABC> !help")
        print(f" OUTPUT: {result}")
        assert result == ParsedCommand(name="help", args=[])

    def test_parse_args_preserve_case(self):
        """Arguments should preserve their case."""
        print("\n INPUT: '!use Claude SONNET'")
        result = parse_command("!use Claude SONNET")
        print(f" OUTPUT: {result}")
        assert result == ParsedCommand(name="use", args=["Claude", "SONNET"])
