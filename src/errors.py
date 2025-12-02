"""Custom exception hierarchy for Cockpit Coder."""


class CockpitError(Exception):
    """Base error type."""


class ProjectNotFound(CockpitError):
    pass


class SessionNotFound(CockpitError):
    pass


class AgentNotFound(CockpitError):
    pass


class CommandNotFound(CockpitError):
    pass


class ProcessError(CockpitError):
    pass


class ConfigError(CockpitError):
    pass


class SlackError(CockpitError):
    pass


class GitHubError(CockpitError):
    pass
