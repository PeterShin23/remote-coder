"""Adapter implementations for Remote Coder."""

from .base import AgentAdapter, AgentResult, FileEdit
from .claude_adapter import ClaudeAdapter
from .codex_adapter import CodexAdapter
from .gemini_adapter import GeminiAdapter

__all__ = [
    "AgentAdapter",
    "AgentResult",
    "FileEdit",
    "ClaudeAdapter",
    "CodexAdapter",
    "GeminiAdapter",
]
