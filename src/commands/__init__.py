"""Commands module for remote-coder CLI."""

from .config_agents import run_config_agents_command
from .config_github import run_config_github_command
from .config_projects import run_config_projects_command
from .config_slack import run_config_slack_command
from .init import run_init_command

__all__ = [
    "run_init_command",
    "run_config_agents_command",
    "run_config_slack_command",
    "run_config_github_command",
    "run_config_projects_command",
]
