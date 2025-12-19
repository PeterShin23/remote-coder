"""Custom exception hierarchy for Remote Coder."""


class RemoteCoderError(Exception):
    """Base error type."""


class ProjectNotFound(RemoteCoderError):
    pass


class SessionNotFound(RemoteCoderError):
    pass


class AgentNotFound(RemoteCoderError):
    pass


class CommandNotFound(RemoteCoderError):
    pass


class ProcessError(RemoteCoderError):
    pass


class ConfigError(RemoteCoderError):
    pass


class SlackError(RemoteCoderError):
    pass


class GitHubError(RemoteCoderError):
    pass


class ProjectCreationError(RemoteCoderError):
    """Raised when project creation fails."""
    pass


class RepoExistsError(ProjectCreationError):
    """Raised when GitHub repo name already exists."""
    pass


class LocalDirNotGitRepoError(ProjectCreationError):
    """Raised when local directory exists but is not a git repository."""
    pass
