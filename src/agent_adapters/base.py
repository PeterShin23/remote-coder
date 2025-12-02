"""Adapter abstractions for one-shot agent executions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence


@dataclass
class FileEdit:
    """Represents a single file edit reported by an agent."""

    path: str
    type: str  # e.g. "edit", "create", "delete"
    diff: str | None = None


@dataclass
class AgentResult:
    """Normalized result payload returned by adapters."""

    success: bool
    output_text: str
    file_edits: List[FileEdit] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    session_context: Dict[str, Any] = field(default_factory=dict)
    raw_output: str = ""


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

