"""Configuration loader."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

import yaml

from .errors import AgentNotFound, ConfigError, ProjectNotFound
from .models import (
    Agent,
    AgentKind,
    GitHubRepoConfig,
    Project,
    WorkingDirMode,
)

LOGGER = logging.getLogger(__name__)


@dataclass
class Config:
    projects: Dict[str, Project]
    agents: Dict[str, Agent]
    slack_bot_token: str
    slack_app_token: str
    slack_allowed_user_id: str
    github_token: str | None = None

    def get_project_by_channel(self, channel: str) -> Project:
        try:
            return self.projects[channel]
        except KeyError as exc:
            raise ProjectNotFound(channel) from exc

    def get_project(self, project_id: str) -> Project:
        try:
            return self.projects[project_id]
        except KeyError as exc:
            raise ProjectNotFound(project_id) from exc

    def get_agent(self, agent_id: str) -> Agent:
        try:
            return self.agents[agent_id]
        except KeyError as exc:
            raise AgentNotFound(agent_id) from exc


def load_config(base_dir: Path | None = None) -> Config:
    root = base_dir or Path(__file__).resolve().parents[1]
    projects = _load_projects(root / "config" / "projects.yaml")
    agents = _load_agents(root / "config" / "agents.yaml")

    slack_bot_token = _require_env("SLACK_BOT_TOKEN")
    slack_app_token = _require_env("SLACK_APP_TOKEN")
    slack_allowed_user_id = _require_env("SLACK_ALLOWED_USER_ID")
    github_token = os.getenv("GITHUB_TOKEN")

    return Config(
        projects=projects,
        agents=agents,
        slack_bot_token=slack_bot_token,
        slack_app_token=slack_app_token,
        slack_allowed_user_id=slack_allowed_user_id,
        github_token=github_token,
    )


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigError(f"{name} is not set")
    return value


def _load_projects(path: Path) -> Dict[str, Project]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Failed to read {path}: {exc}") from exc

    base_dir = Path(data["base_dir"])
    projects = {}
    for project_id, cfg in data.get("projects", {}).items():
        full_path = (base_dir / Path(cfg["path"])).expanduser().resolve()
        if not full_path.exists():
            LOGGER.warning("Project path does not exist for %s: %s", project_id, full_path)

        github_cfg = cfg.get("github")
        github = (
            GitHubRepoConfig(
                owner=github_cfg["owner"],
                repo=github_cfg["repo"],
                default_base_branch=github_cfg["default_base_branch"],
            )
            if github_cfg
            else None
        )

        projects[project_id] = Project(
            id=project_id,
            channel_name=project_id,
            path=full_path,
            default_agent_id=cfg["default_agent"],
            github=github,
        )
    return projects


def _load_agents(path: Path) -> Dict[str, Agent]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Failed to read {path}: {exc}") from exc

    agents = {}
    for agent_id, cfg in data.get("agents", {}).items():
        working_mode, fixed_path = _parse_working_dir_mode(cfg.get("working_dir_mode"))
        agents[agent_id] = Agent(
            id=agent_id,
            kind=AgentKind(cfg.get("kind", "cli")),
            command=cfg["command"],
            working_dir_mode=working_mode,
            fixed_path=fixed_path,
        )
    return agents


def _parse_working_dir_mode(value) -> Tuple[WorkingDirMode, Path | None]:
    if value in (None, "project"):
        return WorkingDirMode.PROJECT, None
    if isinstance(value, str) and value.lower() == "project":
        return WorkingDirMode.PROJECT, None
    if isinstance(value, dict) and "fixed" in value:
        return WorkingDirMode.FIXED, Path(value["fixed"]).expanduser().resolve()
    raise ConfigError(f"Unsupported working_dir_mode: {value}")
