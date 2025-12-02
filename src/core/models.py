"""Domain models for Cockpit Coder."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4


class AgentType(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"


class WorkingDirMode(Enum):
    PROJECT = "project"
    FIXED = "fixed"


@dataclass
class GitHubRepoConfig:
    owner: str
    repo: str
    default_base_branch: str


@dataclass
class Project:
    id: str
    channel_name: str
    path: Path
    default_agent_id: str
    github: Optional[GitHubRepoConfig] = None


class SessionStatus(str, Enum):
    ACTIVE = "active"
    ENDED = "ended"


@dataclass
class Agent:
    id: str
    type: AgentType
    command: List[str]
    working_dir_mode: WorkingDirMode
    fixed_path: Optional[Path] = None
    env: Dict[str, str] = field(default_factory=dict)


@dataclass
class ConversationMessage:
    role: str
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Session:
    project_id: str
    channel_id: str
    thread_ts: str
    active_agent_id: str
    active_agent_type: AgentType
    project_path: Path
    conversation_history: List[ConversationMessage] = field(default_factory=list)
    session_context: Dict[str, Any] = field(default_factory=dict)
    status: SessionStatus = SessionStatus.ACTIVE
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PullRequestRef:
    project_id: str
    session_id: UUID
    number: int
    url: str
    head_branch: str
    base_branch: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CommandArg:
    name: str
    arg_type: str
    required: bool
    description: Optional[str] = None


@dataclass
class CommandDefinition:
    id: str
    title: str
    args: List[CommandArg]
    body: str
    description: Optional[str] = None
    category: Optional[str] = None
