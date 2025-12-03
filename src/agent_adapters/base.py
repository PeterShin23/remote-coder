"""Adapter abstractions for one-shot agent executions."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

LOGGER = logging.getLogger(__name__)


@dataclass
class FileEdit:
    """Represents a single file edit reported by an agent."""

    path: str
    type: str  # e.g. "edit", "create", "delete"
    diff: str | None = None


@dataclass
class StructuredOutput:
    """Structured output parsed from agent's REMOTE_CODER_OUTPUT JSON."""

    slack_message: str
    pr_title: str
    pr_summary: List[str] = field(default_factory=list)


@dataclass
class AgentResult:
    """Normalized result payload returned by adapters."""

    success: bool
    output_text: str
    file_edits: List[FileEdit] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    session_context: Dict[str, Any] = field(default_factory=dict)
    raw_output: str = ""
    structured_output: StructuredOutput | None = None


def _extract_json_from_text(text: str, start_pos: int) -> str | None:
    """
    Extract a complete JSON object starting from start_pos.
    Handles nested braces correctly.
    """
    if start_pos >= len(text) or text[start_pos] != "{":
        return None

    brace_count = 0
    in_string = False
    escape_next = False

    for i in range(start_pos, len(text)):
        char = text[i]

        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if not in_string:
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    return text[start_pos : i + 1]

    return None


def parse_structured_output(text: str) -> StructuredOutput | None:
    """
    Parse REMOTE_CODER_OUTPUT JSON from agent output.

    Expected format:
    REMOTE_CODER_OUTPUT: {"slack_message": "...", "pr_title": "...", "pr_summary": [...]}

    Returns None if not found or invalid JSON.
    """
    # Find the marker
    marker = "REMOTE_CODER_OUTPUT:"
    marker_pos = text.find(marker)
    if marker_pos == -1:
        LOGGER.warning("No REMOTE_CODER_OUTPUT found in agent response")
        return None

    # Find the start of JSON (first '{' after marker)
    start_pos = marker_pos + len(marker)
    while start_pos < len(text) and text[start_pos].isspace():
        start_pos += 1

    if start_pos >= len(text) or text[start_pos] != "{":
        LOGGER.error("No JSON object found after REMOTE_CODER_OUTPUT marker")
        return None

    # Extract the complete JSON object
    json_str = _extract_json_from_text(text, start_pos)
    if not json_str:
        LOGGER.error("Failed to extract complete JSON object")
        return None

    try:
        data = json.loads(json_str)
        return StructuredOutput(
            slack_message=str(data.get("slack_message", "")),
            pr_title=str(data.get("pr_title", "")),
            pr_summary=list(data.get("pr_summary", [])),
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        LOGGER.error(f"Failed to parse REMOTE_CODER_OUTPUT JSON: {e}")
        LOGGER.error(f"Captured JSON string: {repr(json_str[:500])}")
        LOGGER.error(f"JSON string starts with: {repr(json_str[:50])}")
        return None


class AgentAdapter(ABC):
    """Base adapter interface for CLI-based agents."""

    @abstractmethod
    async def run(
        self,
        *,
        task_text: str,
        project_path: str,
        session_id: str,
        conversation_history: Sequence[Dict[str, Any]],
    ) -> AgentResult:
        """Execute a one-shot task with the underlying agent."""

