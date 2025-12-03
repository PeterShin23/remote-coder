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
