"""Core domain logic for Remote Coder."""

from .config import Config, load_config
from .errors import (
    AgentNotFound,
    RemoteCoderError,
    CommandNotFound,
    ConfigError,
    GitHubError,
    ProcessError,
    ProjectNotFound,
    SessionNotFound,
    SlackError,
)
from .models import (
    Agent,
    AgentType,
    CommandArg,
    CommandDefinition,
    GitHubRepoConfig,
    Project,
    PullRequestRef,
    Session,
    SessionStatus,
    WorkingDirMode,
)
from .router import Router
from .conversation import SessionManager

__all__ = [
    "Config",
    "load_config",
    "Agent",
    "AgentType",
    "CommandArg",
    "CommandDefinition",
    "GitHubRepoConfig",
    "Project",
    "PullRequestRef",
    "Session",
    "SessionStatus",
    "WorkingDirMode",
    "RemoteCoderError",
    "ProjectNotFound",
    "AgentNotFound",
    "CommandNotFound",
    "ProcessError",
    "ConfigError",
    "SlackError",
    "GitHubError",
    "SessionNotFound",
    "Router",
    "SessionManager",
]
