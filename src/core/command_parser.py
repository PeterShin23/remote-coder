"""Lightweight parser for Cockpit commands."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

MENTION_PREFIX = re.compile(r"^<@[^>]+>\s*")


@dataclass
class ParsedCommand:
    name: str
    args: List[str]


def parse_command(text: str) -> Optional[ParsedCommand]:
    """Parse Slack message text into a structured command.

    Supported syntax:
      - Optional mention prefix (<@U123>)
      - Commands prefixed with `!`
    """

    normalized = text.strip()
    normalized = MENTION_PREFIX.sub("", normalized, count=1)
    if not normalized.startswith("!"):
        return None

    parts = normalized[1:].strip().split()
    if not parts:
        return None
    name = parts[0].lower()
    args = parts[1:]
    return ParsedCommand(name=name, args=args)
