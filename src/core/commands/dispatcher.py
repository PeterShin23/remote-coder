"""Command parsing helpers that leverage the central registry."""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Sequence

from .parser import MENTION_PREFIX, ParsedCommand
from .registry import CommandSpec, iter_command_specs


class CommandDispatcher:
    """Maps parsed command names to their metadata."""

    def __init__(self, specs: Optional[Sequence[CommandSpec]] = None) -> None:
        self._specs: Sequence[CommandSpec] = tuple(specs or iter_command_specs())
        self._lookup: Dict[str, CommandSpec] = {
            name: spec for spec in self._specs for name in spec.all_names
        }

    @property
    def specs(self) -> Sequence[CommandSpec]:
        return self._specs

    def get_spec(self, name: str) -> Optional[CommandSpec]:
        return self._lookup.get(name.lower())

    def parse_bot_command(self, text: str) -> Optional[ParsedCommand]:
        """Parse mention-based commands like `@remote-coder help`."""

        normalized = text.strip()
        if not normalized:
            return None
        normalized = MENTION_PREFIX.sub("", normalized, count=1)
        lowered = normalized.lower()
        if lowered.startswith("@remote-coder"):
            normalized = normalized[len("@remote-coder") :].strip()
            lowered = normalized.lower()
        if lowered.startswith("remote-coder"):
            normalized = normalized[len("remote-coder") :].strip()
        if not normalized:
            return None

        parts = normalized.split()
        if not parts:
            return None

        name = parts[0].lower()
        if name not in self._lookup:
            return None
        return ParsedCommand(name=name, args=parts[1:])

    def build_help_lines(self) -> list[str]:
        """Render help text for all commands."""

        lines = ["Available commands:"]
        for spec in self._specs:
            alias_hint = spec.alias_display()
            lines.append(f"- `{spec.usage}` – {spec.description}{alias_hint}")
        lines.append("")
        lines.append("Send any other message to run the current agent once with that request.")
        return lines
