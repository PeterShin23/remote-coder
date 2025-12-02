"""Domain models for Cockpit Coder."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import List, Optional
from uuid import UUID, uuid4


class AgentKind(str, Enum):
    CLI = "cli"


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


@dataclass
class Agent:
    id: str
    kind: AgentKind
    command: List[str]
    working_dir_mode: WorkingDirMode
    fixed_path: Optional[Path] = None


class SessionStatus(str, Enum):
    ACTIVE = "active"
    ENDED = "ended"


@dataclass
class Session:
    project_id: str
    slack_channel: str
    slack_thread_ts: str
    active_agent_id: str
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
