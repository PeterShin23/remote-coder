"""Configuration loader."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

import yaml
from dotenv import load_dotenv

from .errors import AgentNotFound, ConfigError, ProjectNotFound
from .models import Agent, AgentType, GitHubRepoConfig, Project, WorkingDirMode

LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path("~/.remote-coder").expanduser()
ENV_FILE_NAME = ".env"
PROJECTS_FILE = "projects.yaml"
AGENTS_FILE = "agents.yaml"


@dataclass
class Config:
    projects: Dict[str, Project]
    agents: Dict[str, Agent]
    slack_bot_token: str
    slack_app_token: str
    slack_allowed_user_ids: list[str]
    base_dir: Path
    config_dir: Path
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


def resolve_config_dir(config_dir: Path | str | None) -> Path:
    """Resolve and validate the directory containing .env + YAML files."""
    target = (
        Path(config_dir).expanduser() if config_dir else DEFAULT_CONFIG_DIR
    ).resolve()
    if not target.exists():
        raise ConfigError(
            f"Config directory {target} does not exist. "
            "Create it and add .env, projects.yaml, and agents.yaml."
        )
    if not target.is_dir():
        raise ConfigError(f"Config directory {target} is not a directory")
    return target


def load_config(config_dir: Path | str | None = None) -> Config:
    """Load Remote Coder configuration from the provided or default directory."""
    root = resolve_config_dir(config_dir)
    return _load_config_from_root(root)


def _load_config_from_root(root: Path) -> Config:
    _load_env_file(root / ENV_FILE_NAME)

    projects, base_dir = _load_projects(root / PROJECTS_FILE)
    agents = _select_agents(_load_agents(root / AGENTS_FILE))

    slack_bot_token = _require_env("SLACK_BOT_TOKEN")
    slack_app_token = _require_env("SLACK_APP_TOKEN")
    slack_allowed_user_ids = _load_allowed_user_ids()
    github_token = os.getenv("GITHUB_TOKEN")

    return Config(
        projects=projects,
        agents=agents,
        slack_bot_token=slack_bot_token,
        slack_app_token=slack_app_token,
        slack_allowed_user_ids=slack_allowed_user_ids,
        base_dir=base_dir,
        config_dir=root,
        github_token=github_token,
    )


def _load_env_file(path: Path) -> None:
    if not path.exists():
        LOGGER.warning("No .env file found at %s; relying on shell environment.", path)
        return
    load_dotenv(dotenv_path=path, override=False)


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigError(f"{name} is not set")
    return value


def _load_allowed_user_ids() -> list[str]:
    raw_value = os.getenv("SLACK_ALLOWED_USER_IDS") or os.getenv("SLACK_ALLOWED_USER_ID")
    if not raw_value:
        raise ConfigError("SLACK_ALLOWED_USER_IDS (or SLACK_ALLOWED_USER_ID) must be set")
    return [uid.strip() for uid in raw_value.split(",") if uid.strip()]


def _load_projects(path: Path) -> Tuple[Dict[str, Project], Path]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"projects.yaml not found at {path}") from exc
    except OSError as exc:
        raise ConfigError(f"Failed to read {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"Invalid projects.yaml structure at {path}")

    base_dir_raw = data.get("base_dir")
    if not base_dir_raw:
        raise ConfigError("projects.yaml must define base_dir")
    base_dir = Path(base_dir_raw).expanduser()
    if not base_dir.is_absolute():
        base_dir = (path.parent / base_dir).resolve()
    else:
        base_dir = base_dir.resolve()

    projects = {}
    for project_id, cfg in (data.get("projects") or {}).items():
        if not isinstance(cfg, dict):
            raise ConfigError(f"Project {project_id} must be a mapping")

        rel_path = cfg.get("path")
        if not rel_path:
            raise ConfigError(f"Project {project_id} is missing path")
        full_path = (base_dir / Path(rel_path)).expanduser().resolve()
        if not full_path.exists():
            LOGGER.warning("Project path does not exist for %s: %s", project_id, full_path)

        default_agent = cfg.get("default_agent")
        if not default_agent:
            raise ConfigError(f"Project {project_id} missing default_agent")

        default_model = cfg.get("default_model")

        github_cfg = cfg.get("github")
        github = None
        if github_cfg:
            try:
                github = GitHubRepoConfig(
                    owner=github_cfg["owner"],
                    repo=github_cfg["repo"],
                    default_base_branch=github_cfg["default_base_branch"],
                )
            except KeyError as exc:
                raise ConfigError(f"Incomplete GitHub config for {project_id}") from exc

        projects[project_id] = Project(
            id=project_id,
            channel_name=project_id,
            path=full_path,
            default_agent_id=default_agent,
            default_model=default_model,
            github=github,
        )
    if not projects:
        LOGGER.warning("No projects configured in %s", path)
    return projects, base_dir


def _load_agents(path: Path) -> Dict[str, Agent]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"agents.yaml not found at {path}") from exc
    except OSError as exc:
        raise ConfigError(f"Failed to read {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"Invalid agents.yaml structure at {path}")

    agents = {}
    for agent_id, cfg in (data.get("agents") or {}).items():
        if not isinstance(cfg, dict):
            raise ConfigError(f"Agent {agent_id} must be a mapping")

        working_mode, fixed_path = _parse_working_dir_mode(cfg.get("working_dir_mode"))
        agent_type_raw = cfg.get("type")
        if not agent_type_raw:
            raise ConfigError(f"Agent {agent_id} is missing required type field")
        try:
            agent_type = AgentType(agent_type_raw.lower())
        except ValueError as exc:
            raise ConfigError(f"Unsupported agent type {agent_type_raw} for {agent_id}") from exc

        command = cfg.get("command")
        if not isinstance(command, list) or not command:
            raise ConfigError(f"Agent {agent_id} must supply a non-empty command list")

        env = cfg.get("env") or {}
        if not isinstance(env, dict):
            raise ConfigError(f"env for agent {agent_id} must be a mapping")

        models = cfg.get("models") or {}
        if not isinstance(models, dict):
            raise ConfigError(f"models for agent {agent_id} must be a mapping")

        agents[agent_id] = Agent(
            id=agent_id,
            type=agent_type,
            command=command,
            working_dir_mode=working_mode,
            fixed_path=fixed_path,
            env={str(k): str(v) for k, v in env.items()},
            models=models,
        )
    if not agents:
        LOGGER.warning("No agents configured in %s", path)
    return agents


def _select_agents(all_agents: Dict[str, Agent]) -> Dict[str, Agent]:
    raw = (os.getenv("REMOTE_CODER_AGENTS") or "").strip()
    if not raw:
        return all_agents

    requested = [name.strip() for name in raw.split(",") if name.strip()]
    missing = [name for name in requested if name not in all_agents]
    if missing:
        raise ConfigError(
            "Unknown agent(s) requested via REMOTE_CODER_AGENTS: "
            + ", ".join(missing)
        )
    return {name: all_agents[name] for name in requested}


def _parse_working_dir_mode(value) -> Tuple[WorkingDirMode, Path | None]:
    if value in (None, "project"):
        return WorkingDirMode.PROJECT, None
    if isinstance(value, str):
        lowered = value.lower()
        if lowered == "project":
            return WorkingDirMode.PROJECT, None
        if lowered.startswith("fixed:"):
            fixed_path = Path(value.split(":", 1)[1]).expanduser().resolve()
            return WorkingDirMode.FIXED, fixed_path
    if isinstance(value, dict) and "fixed" in value:
        return WorkingDirMode.FIXED, Path(value["fixed"]).expanduser().resolve()
    raise ConfigError(f"Unsupported working_dir_mode: {value}")
