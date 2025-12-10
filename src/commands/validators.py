"""Input validation utilities for remote-coder init command."""

from __future__ import annotations

import re
from pathlib import Path


def validate_slack_bot_token(token: str) -> tuple[bool, str]:
    """Validate SLACK_BOT_TOKEN format (xoxb-*)."""
    if not token:
        return False, "Token is required"
    if not token.startswith("xoxb-"):
        return False, "Token must start with 'xoxb-'"
    if len(token) < 20:
        return False, "Token appears too short"
    return True, ""


def validate_slack_app_token(token: str) -> tuple[bool, str]:
    """Validate SLACK_APP_TOKEN format (xapp-*)."""
    if not token:
        return False, "Token is required"
    if not token.startswith("xapp-"):
        return False, "Token must start with 'xapp-'"
    if len(token) < 20:
        return False, "Token appears too short"
    return True, ""


def validate_slack_user_ids(ids: str) -> tuple[bool, str]:
    """Validate comma-separated Slack user IDs."""
    if not ids:
        return False, "At least one user ID is required"

    parts = [uid.strip() for uid in ids.split(",") if uid.strip()]
    if not parts:
        return False, "At least one user ID is required"

    for uid in parts:
        if not uid.startswith("U"):
            return False, f"User ID '{uid}' should start with 'U'"
        if len(uid) < 8:
            return False, f"User ID '{uid}' appears too short"

    return True, ""


def validate_github_token(token: str) -> tuple[bool, str]:
    """Validate GITHUB_TOKEN format."""
    if not token:
        return True, ""  # Optional token

    valid_prefixes = ("ghp_", "github_pat_", "gho_")
    if not token.startswith(valid_prefixes):
        return False, f"Token should start with one of: {', '.join(valid_prefixes)}"

    if len(token) < 20:
        return False, "Token appears too short"

    return True, ""


def validate_directory_path(path: str) -> tuple[bool, str]:
    """Validate directory path exists or can be created."""
    if not path:
        return False, "Path is required"

    try:
        p = Path(path).expanduser().resolve()

        if p.exists() and not p.is_dir():
            return False, f"Path exists but is not a directory: {p}"

        # Check if parent exists (to ensure we can create the directory)
        if not p.exists():
            parent = p.parent
            if not parent.exists():
                return False, f"Parent directory doesn't exist: {parent}"

        return True, ""
    except Exception as e:
        return False, f"Invalid path: {e}"


def validate_channel_name(name: str) -> tuple[bool, str]:
    """Validate Slack channel name format."""
    if not name:
        return False, "Channel name is required"

    # Slack channel names: lowercase, alphanumeric + hyphens/underscores
    if not re.match(r"^[a-z0-9_-]+$", name):
        return False, "Use lowercase letters, numbers, hyphens, and underscores only"

    if len(name) > 80:
        return False, "Channel name too long (max 80 characters)"

    if len(name) < 1:
        return False, "Channel name too short"

    return True, ""


def validate_agent_name(name: str, available: list[str]) -> tuple[bool, str]:
    """Validate agent name is in available list."""
    if not name:
        return False, "Agent name is required"

    if name not in available:
        return False, f"Agent must be one of: {', '.join(available)}"

    return True, ""


def validate_project_path(path: str) -> tuple[bool, str]:
    """Validate project path (can be relative)."""
    if not path:
        return False, "Project path is required"

    # Allow relative paths, just check for obviously invalid characters
    if any(char in path for char in ["\0", "\n", "\r"]):
        return False, "Path contains invalid characters"

    return True, ""


def validate_github_owner(owner: str) -> tuple[bool, str]:
    """Validate GitHub owner/organization name."""
    if not owner:
        return True, ""  # Optional

    # GitHub username/org rules: alphanumeric + hyphens, can't start with hyphen
    if not re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$", owner):
        return False, "Invalid GitHub owner format (alphanumeric and hyphens only)"

    if len(owner) > 39:
        return False, "GitHub owner name too long (max 39 characters)"

    return True, ""


def validate_github_repo(repo: str) -> tuple[bool, str]:
    """Validate GitHub repository name."""
    if not repo:
        return True, ""  # Optional

    # GitHub repo rules: alphanumeric + hyphens/underscores/dots
    if not re.match(r"^[a-zA-Z0-9._-]+$", repo):
        return False, "Invalid GitHub repo format (alphanumeric, hyphens, underscores, dots only)"

    if len(repo) > 100:
        return False, "GitHub repo name too long (max 100 characters)"

    return True, ""


def validate_branch_name(branch: str) -> tuple[bool, str]:
    """Validate git branch name."""
    if not branch:
        return False, "Branch name is required"

    # Basic git branch name validation
    invalid_chars = [" ", "~", "^", ":", "?", "*", "[", "\\", ".."]
    for char in invalid_chars:
        if char in branch:
            return False, f"Branch name cannot contain '{char}'"

    if branch.startswith("/") or branch.endswith("/"):
        return False, "Branch name cannot start or end with '/'"

    if branch.endswith("."):
        return False, "Branch name cannot end with '.'"

    return True, ""
