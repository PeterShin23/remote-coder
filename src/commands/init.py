"""Interactive initialization command for remote-coder."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import requests
import yaml

from .config_github import (
    run_config_github_command,
    update_env_github_config,
    validate_github_token_api,
)
from .config_slack import (
    SLACK_APP_MANIFEST,
    run_config_slack_command,
    update_env_slack_config,
    validate_slack_bot_token_api,
)
from .utils import detect_dev_mode, sync_to_home_config
from .validators import (
    validate_agent_name,
    validate_branch_name,
    validate_channel_name,
    validate_directory_path,
    validate_github_owner,
    validate_github_repo,
    validate_github_token,
    validate_project_path,
    validate_slack_app_token,
    validate_slack_bot_token,
    validate_slack_user_ids,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path("~/.remote-coder").expanduser()
AVAILABLE_AGENTS = ["claude", "codex", "gemini"]

# Embedded agents.yaml template as fallback when GitHub download fails
EMBEDDED_AGENTS_YAML = """# Define which CLI agents are available. Each entry describes the adapter type
# plus the command invocation that should be executed.

agents:
  claude:
    type: claude
    # opus (claude-opus-4.5), sonnet (claude-sonnet-4.5), haiku (claude-haiku-4.5)
    models:
      default: sonnet
      available: [opus, sonnet, haiku]
    command:
      - claude
      - --print
      - --permission-mode
      - acceptEdits
      - --output-format
      - stream-json
      - --verbose
    working_dir_mode: project

  codex:
    type: codex
    # base (gpt-5.1-codex), max (gpt-5.1-codex-max)
    models:
      default: base
      available: [base, max]
    command:
      - codex
      - exec
      - --sandbox
      - workspace-write
      - --json
      # WARNING: Be careful of prompt injection when using web search with codex!
      # To disable web search, comment out the configs below.
      - --config
      - features.web_search_request=true
      - --config
      - sandbox_workspace_write.network_access=true
    working_dir_mode: project

  gemini:
    type: gemini
    # pro (gemini-2.5-pro), flash (gemini-2.5-flash)
    models:
      default: auto
      available: [auto, pro, flash]
    command:
      - gemini
      - --approval-mode
      - auto_edit
      - --output-format
      - stream-json
    working_dir_mode: project
"""


@dataclass
class ProjectConfig:
    """Configuration for a single project."""

    channel_name: str
    path: str
    default_agent: str
    github_owner: str | None = None
    github_repo: str | None = None
    default_base_branch: str = "main"


@dataclass
class ConfigData:
    """Complete configuration data collected from user."""

    slack_bot_token: str
    slack_app_token: str
    slack_allowed_user_ids: str
    github_token: str | None
    base_dir: str
    projects: list[ProjectConfig] = field(default_factory=list)


def prompt_with_validation(
    prompt_text: str,
    validator: Callable[[str], tuple[bool, str]],
    required: bool = True,
    default: str | None = None,
) -> str:
    """
    Prompt user for input with validation and retry logic.

    Args:
        prompt_text: The prompt to display to the user
        validator: Function that validates input and returns (is_valid, error_message)
        required: Whether the input is required (empty string not allowed)
        default: Default value if user presses Enter (shown in prompt)

    Returns:
        Validated user input
    """
    if default:
        prompt_text = f"{prompt_text} [{default}]"
    prompt_text = f"{prompt_text}: "

    while True:
        try:
            user_input = input(prompt_text).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nInitialization cancelled.")
            raise SystemExit(0)

        # Use default if provided and user pressed Enter
        if not user_input and default:
            user_input = default

        # Check if required
        if required and not user_input:
            print("Error: This field is required.\n")
            continue

        # Skip validation for optional empty inputs
        if not required and not user_input:
            return user_input

        # Validate input
        is_valid, error_msg = validator(user_input)
        if is_valid:
            return user_input
        else:
            print(f"Error: {error_msg}\n")


def run_slack_guided_setup() -> dict[str, str]:
    """
    Run guided Slack setup flow inline within init.

    Returns dict with bot_token, app_token, user_ids.
    """
    import json
    import urllib.parse
    import webbrowser

    print("\n" + "-" * 60)
    print("Guided Slack Setup")
    print("-" * 60)

    # Check if user has existing app
    print("\nDo you have an existing Slack app configured for Remote Coder?")
    has_app = input("(y/N): ").strip().lower()

    if has_app != "y":
        # Check if they have a workspace
        print("\nDo you have a Slack workspace where you want to install Remote Coder?")
        has_workspace = input("(Y/n): ").strip().lower()

        if has_workspace == "n":
            print("\nYou'll need to create a Slack workspace first:")
            print("  1. Visit https://slack.com/create")
            print("  2. Follow the steps to create a new workspace")
            print("  3. Come back here when done")
            input("\nPress Enter after creating your workspace...")

        print("\nWe'll create a Slack app with all required settings pre-configured:")
        print("  • Socket Mode enabled")
        print("  • Bot scopes: app_mentions:read, channels:history, channels:read, chat:write")
        print("  • Event subscriptions: app_mention, message.channels")

        # Show manifest for manual use
        print("\nHere's the app manifest (in case you need it):")
        print("-" * 60)
        manifest_json = json.dumps(SLACK_APP_MANIFEST, indent=2)
        print(manifest_json)
        print("-" * 60)

        # Create manifest URL
        manifest_encoded = urllib.parse.quote(json.dumps(SLACK_APP_MANIFEST))
        create_app_url = f"https://api.slack.com/apps?new_app=1&manifest_json={manifest_encoded}"

        input("\nPress Enter to open Slack's app creation page...")

        try:
            webbrowser.open(create_app_url)
            print("\n✓ Browser opened to Slack app creation page")
        except Exception:
            print(f"\n⚠ Could not open browser. Please visit:")
            print(f"  {create_app_url}")

        print("\nIn the browser:")
        print("  1. Select your workspace")
        print("  2. Review the app configuration (should be pre-filled)")
        print("  3. Click 'Create'")
        print("\nIf the manifest isn't pre-filled, click 'Create from manifest'")
        print("and paste the JSON shown above.")

        input("\nPress Enter after creating the app...")

    # Step 2: App-Level Token
    print("\n" + "-" * 60)
    print("Step: Generate App-Level Token")
    print("-" * 60)

    try:
        webbrowser.open("https://api.slack.com/apps")
        print("\n✓ Browser opened to Slack apps page")
    except Exception:
        print("\nPlease go to: https://api.slack.com/apps")

    print("\nIn your app settings:")
    print("  1. Click on your app (Remote Coder)")
    print("  2. Go to 'Basic Information' in the left sidebar")
    print("  3. Scroll down to 'App-Level Tokens'")
    print("  4. Click 'Generate Token and Scopes'")
    print("  5. Name it (e.g., 'socket-mode')")
    print("  6. Add scope: connections:write")
    print("  7. Click 'Generate'")
    print("  8. Copy the token (starts with xapp-)")

    slack_app_token = prompt_with_validation(
        "\nPaste your App-Level Token (xapp-...)",
        validate_slack_app_token,
        required=True,
    )
    print("✓ App token received")

    # Step 3: Bot Token
    print("\n" + "-" * 60)
    print("Step: Install App & Get Bot Token")
    print("-" * 60)

    print("\nIn your app settings:")
    print("  1. Go to 'OAuth & Permissions' in the left sidebar")
    print("  2. Click 'Install to Workspace' (or 'Reinstall' if needed)")
    print("  3. Authorize the app")
    print("  4. Copy the 'Bot User OAuth Token' (starts with xoxb-)")

    slack_bot_token = prompt_with_validation(
        "\nPaste your Bot User OAuth Token (xoxb-...)",
        validate_slack_bot_token,
        required=True,
    )

    # Validate bot token
    print("\n→ Validating bot token...")
    is_valid, error, auth_data = validate_slack_bot_token_api(slack_bot_token)
    if is_valid and auth_data:
        print(f"✓ Bot token valid! Team: {auth_data.get('team', 'Unknown')}")
    else:
        print(f"⚠ Could not validate token: {error}")
        print("  Continuing anyway...")

    # Step 4: User IDs
    print("\n" + "-" * 60)
    print("Step: Configure Allowed Users")
    print("-" * 60)

    print("\nTo find your Slack User ID:")
    print("  1. Click on your profile picture in Slack")
    print("  2. Click 'Profile'")
    print("  3. Click the '...' menu")
    print("  4. Select 'Copy member ID'")

    slack_user_ids = prompt_with_validation(
        "\nEnter allowed Slack user IDs (comma-separated)",
        validate_slack_user_ids,
        required=True,
    )

    print("\n✓ Slack configuration complete!")

    return {
        "bot_token": slack_bot_token,
        "app_token": slack_app_token,
        "user_ids": slack_user_ids,
    }


def run_github_guided_setup() -> dict[str, str | None]:
    """
    Run guided GitHub setup flow inline within init.

    Returns dict with token (may be None if skipped).
    """
    import webbrowser

    print("\n" + "-" * 60)
    print("Guided GitHub Setup")
    print("-" * 60)

    print("\nDo you have an existing GitHub Personal Access Token?")
    has_token = input("(y/N): ").strip().lower()

    if has_token != "y":
        print("\nYou can create either:")
        print("  [1] Fine-grained token (recommended) - scoped to specific repos")
        print("  [2] Classic token - broader access")

        token_type = input("\nYour choice (1/2) [1]: ").strip()

        if token_type == "2":
            url = "https://github.com/settings/tokens/new?description=Remote%20Coder&scopes=repo"
            print("\nRequired scope: 'repo' (Full control of private repositories)")
        else:
            url = "https://github.com/settings/personal-access-tokens/new"
            print("\nConfigure with:")
            print("  • Repository access: select repos Remote Coder will manage")
            print("  • Permissions: Contents (R/W), Pull requests (R/W)")

        input("\nPress Enter to open browser...")

        try:
            webbrowser.open(url)
            print("✓ Browser opened")
        except Exception:
            print(f"⚠ Please visit: {url}")

        print("\nCreate the token, then copy it.")

    github_token = prompt_with_validation(
        "\nPaste your GitHub token (or press Enter to skip)",
        validate_github_token,
        required=False,
    )

    if github_token:
        print("\n→ Validating token...")
        is_valid, error, user_data = validate_github_token_api(github_token)
        if is_valid and user_data:
            print(f"✓ Token valid! Authenticated as: {user_data.get('login', 'Unknown')}")
        else:
            print(f"⚠ Could not validate: {error}")
            print("  Continuing anyway...")

        print("\n✓ GitHub configuration complete!")
    else:
        print("\n→ Skipping GitHub setup (can configure later with 'remote-coder config github')")

    return {"token": github_token if github_token else None}


def interactive_setup() -> ConfigData:
    """Run interactive prompts to collect all configuration values."""
    print("\n" + "=" * 60)
    print("Welcome to Remote Coder!")
    print("=" * 60)
    print("\nThis wizard will help you set up your configuration.")
    print("\nYou'll need:")
    print("  - Slack bot token (xoxb-*) and app token (xapp-*)")
    print("  - At least one Slack user ID")
    print("  - GitHub personal access token (for PR management)")
    print("  - Path to your projects directory")
    print("\nLet's get started!\n")

    # Slack configuration
    print("Slack Configuration")
    print("-" * 60)
    print("\nHow would you like to set up Slack?")
    print("  [1] Guided setup (opens browser, walks you through each step)")
    print("  [2] Manual setup (paste tokens you already have)")

    slack_setup_method = input("\nYour choice (1/2) [1]: ").strip()
    if slack_setup_method == "2":
        # Manual setup - original flow
        slack_bot_token = prompt_with_validation(
            "Enter your SLACK_BOT_TOKEN (starts with xoxb-)",
            validate_slack_bot_token,
            required=True,
        )
        slack_app_token = prompt_with_validation(
            "Enter your SLACK_APP_TOKEN (starts with xapp-)",
            validate_slack_app_token,
            required=True,
        )
        slack_allowed_user_ids = prompt_with_validation(
            "Enter allowed Slack user IDs (comma-separated)",
            validate_slack_user_ids,
            required=True,
        )
    else:
        # Guided setup
        slack_result = run_slack_guided_setup()
        slack_bot_token = slack_result["bot_token"]
        slack_app_token = slack_result["app_token"]
        slack_allowed_user_ids = slack_result["user_ids"]

    # GitHub configuration
    print("\nGitHub Configuration")
    print("-" * 60)
    print("\nGitHub integration enables automatic PR creation and management.")
    print("\nHow would you like to set up GitHub?")
    print("  [1] Guided setup (opens browser, walks you through token creation)")
    print("  [2] Manual setup (paste a token you already have)")
    print("  [3] Skip (set up later with 'remote-coder config github')")

    github_setup_method = input("\nYour choice (1/2/3) [1]: ").strip()
    if github_setup_method == "3":
        github_token = None
    elif github_setup_method == "2":
        # Manual setup - original flow
        github_token = prompt_with_validation(
            "Enter your GITHUB_TOKEN (starts with ghp_, github_pat_, or gho_)",
            validate_github_token,
            required=False,
        )
    else:
        # Guided setup
        github_result = run_github_guided_setup()
        github_token = github_result.get("token")

    # Projects configuration
    print("\nProjects Configuration")
    print("-" * 60)
    print("The base directory is the parent folder containing your project repositories.")
    print("For each project, you'll provide a path relative to this base directory.")
    print(f"Example: If base_dir is /Users/you/code and project path is 'myapp',")
    print(f"         the full path will be /Users/you/code/myapp")
    base_dir = prompt_with_validation(
        "\nEnter base directory for your projects",
        validate_directory_path,
        required=True,
    )

    # Expand and resolve base_dir
    base_dir_path = Path(base_dir).expanduser().resolve()

    # Check if base_dir exists, offer to create if not
    if not base_dir_path.exists():
        create = input(f"\nDirectory doesn't exist: {base_dir_path}\nCreate it now? (Y/n): ")
        if create.lower() != "n":
            try:
                base_dir_path.mkdir(parents=True, exist_ok=True)
                print(f"Created directory: {base_dir_path}")
            except Exception as e:
                print(f"Error: Failed to create directory: {e}")
                raise SystemExit(1)
        else:
            print("Error: Base directory must exist.")
            raise SystemExit(1)

    base_dir = str(base_dir_path)

    # Collect projects
    projects = []
    while True:
        if projects:
            print(f"\n--- Project {len(projects) + 1} ---")
        else:
            print("\n--- First Project ---")

        channel_name = prompt_with_validation(
            "Enter Slack channel name",
            validate_channel_name,
            required=True,
        )
        print(f"\nEnter the project directory name (relative to {base_dir})")
        print(f"Example: If your project is at {base_dir}/my-app, enter: my-app")
        project_path = prompt_with_validation(
            "Project path",
            validate_project_path,
            required=True,
        )
        default_agent = prompt_with_validation(
            f"Select default agent ({'/'.join(AVAILABLE_AGENTS)})",
            lambda x: validate_agent_name(x, AVAILABLE_AGENTS),
            required=True,
        )

        # GitHub info (optional, depends on whether they provided a token)
        github_owner = None
        github_repo = None
        default_base_branch = "main"

        if github_token:
            print("\nGitHub repository info (optional - press Enter to skip):")
            github_owner = prompt_with_validation(
                "Enter GitHub owner/organization",
                validate_github_owner,
                required=False,
            )
            if github_owner:
                github_repo = prompt_with_validation(
                    "Enter GitHub repository name",
                    validate_github_repo,
                    required=False,
                )
                if github_repo:
                    default_base_branch = prompt_with_validation(
                        "Enter default base branch",
                        validate_branch_name,
                        required=True,
                        default="main",
                    )

        projects.append(
            ProjectConfig(
                channel_name=channel_name,
                path=project_path,
                default_agent=default_agent,
                github_owner=github_owner if github_owner else None,
                github_repo=github_repo if github_repo else None,
                default_base_branch=default_base_branch,
            )
        )

        # Ask if they want to add more projects
        add_more = input("\nAdd another project? (y/N): ").strip().lower()
        if add_more != "y":
            break

    return ConfigData(
        slack_bot_token=slack_bot_token,
        slack_app_token=slack_app_token,
        slack_allowed_user_ids=slack_allowed_user_ids,
        github_token=github_token if github_token else None,
        base_dir=base_dir,
        projects=projects,
    )


def download_agents_yaml(target_path: Path) -> None:
    """
    Download agents.yaml from GitHub repository.

    Falls back to embedded template if download fails.
    """
    url = "https://raw.githubusercontent.com/PeterShin23/remote-coder/main/config/agents.yaml"

    try:
        LOGGER.info("Downloading agents.yaml from GitHub...")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        target_path.write_text(response.text, encoding="utf-8")
        print(f"Downloaded agents.yaml from GitHub")
    except requests.RequestException as exc:
        LOGGER.warning("Failed to download agents.yaml: %s", exc)
        print(f"Warning: Could not download from GitHub, using embedded template")
        target_path.write_text(EMBEDDED_AGENTS_YAML, encoding="utf-8")
        print(f"Using embedded agents.yaml template")


def generate_env_file(path: Path, config: ConfigData) -> None:
    """Generate .env file from config data."""
    lines = [
        "# Remote Coder Configuration",
        "# Generated by remote-coder init",
        f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "# Slack Configuration",
        f"SLACK_BOT_TOKEN={config.slack_bot_token}",
        f"SLACK_APP_TOKEN={config.slack_app_token}",
        f"SLACK_ALLOWED_USER_IDS={config.slack_allowed_user_ids}",
        "",
    ]

    if config.github_token:
        lines.extend(
            [
                "# GitHub Configuration",
                f"GITHUB_TOKEN={config.github_token}",
                "",
            ]
        )

    lines.extend(
        [
            "# Logging (optional)",
            "# Standard logging levels: DEBUG, INFO, WARNING, ERROR",
            "LOG_LEVEL=INFO",
            "",
            "# Agent filtering (optional)",
            "# Leave empty to enable every agent defined in agents.yaml",
            "# REMOTE_CODER_AGENTS=claude,codex,gemini",
            "",
        ]
    )

    path.write_text("\n".join(lines), encoding="utf-8")
    # Set restrictive permissions on .env file (secrets)
    path.chmod(0o600)


def generate_projects_yaml(path: Path, config: ConfigData) -> None:
    """Generate projects.yaml from config data."""
    data = {"base_dir": config.base_dir, "projects": {}}

    for project in config.projects:
        project_data = {
            "path": project.path,
            "default_agent": project.default_agent,
        }

        if project.github_owner and project.github_repo:
            project_data["github"] = {
                "owner": project.github_owner,
                "repo": project.github_repo,
                "default_base_branch": project.default_base_branch,
            }

        data["projects"][project.channel_name] = project_data

    with path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    # Set restrictive permissions
    path.chmod(0o600)


def print_summary(config: ConfigData, target_dir: Path) -> None:
    """Print configuration summary before writing files."""
    print("\n" + "=" * 60)
    print("Configuration Summary")
    print("=" * 60)
    print(f"\nConfig directory: {target_dir}")
    print(f"Base directory: {config.base_dir}")
    print(f"\nProjects ({len(config.projects)}):")
    for proj in config.projects:
        print(f"  - {proj.channel_name} (agent: {proj.default_agent})")
        print(f"    Path: {config.base_dir}/{proj.path}")
        if proj.github_owner and proj.github_repo:
            print(f"    GitHub: {proj.github_owner}/{proj.github_repo}")
    print(f"\nSlack:")
    user_ids = config.slack_allowed_user_ids.split(",")
    print(f"  - Allowed user IDs: {', '.join(uid.strip() for uid in user_ids)}")
    if config.github_token:
        print(f"\nGitHub integration: Enabled")
    else:
        print(f"\nGitHub integration: Disabled")
    print()


def check_existing_config(target_dir: Path) -> bool:
    """
    Check if config directory exists and prompt user to overwrite.

    Returns:
        True if we should proceed (either new dir or user confirmed overwrite)
        False if user declined to overwrite
    """
    if not target_dir.exists():
        return True

    print(f"\nConfiguration directory already exists: {target_dir}\n")
    print("Existing files:")
    for file in [".env", "projects.yaml", "agents.yaml"]:
        exists = (target_dir / file).exists()
        symbol = "✓" if exists else "✗"
        print(f"  {symbol} {file}")

    try:
        response = input("\nOverwrite existing configuration? (y/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nInitialization cancelled.")
        return False

    if response != "y":
        print("Initialization cancelled.")
        return False

    # Create backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = target_dir / f"backup_{timestamp}"
    backup_dir.mkdir(exist_ok=True)

    files_backed_up = []
    for file in [".env", "projects.yaml", "agents.yaml"]:
        src = target_dir / file
        if src.exists():
            shutil.copy2(src, backup_dir / file)
            files_backed_up.append(file)

    if files_backed_up:
        print(f"\nBacked up existing files to: {backup_dir}")
        print(f"Files backed up: {', '.join(files_backed_up)}\n")

    return True


def run_init_command(args) -> int:
    """
    Main entry point for the init command.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit status code (0 for success, 1 for error)
    """
    # Detect dev mode
    is_dev_mode, project_root = detect_dev_mode()

    if is_dev_mode and project_root:
        target_dir = project_root
        print(f"\n[Dev mode detected - will update {target_dir}]")
    else:
        target_dir = DEFAULT_CONFIG_DIR

    # Check if directory exists and handle overwrite
    if not check_existing_config(target_dir):
        return 0

    # Collect configuration from user
    try:
        config = interactive_setup()
    except (KeyboardInterrupt, EOFError):
        print("\nInitialization cancelled.")
        return 0

    # Show summary and confirm
    print_summary(config, target_dir)
    try:
        confirm = input("Create configuration? (Y/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nInitialization cancelled.")
        return 0

    if confirm == "n":
        print("Initialization cancelled.")
        return 0

    # Determine file paths based on dev/user mode
    if is_dev_mode and project_root:
        env_path = target_dir / ".env"
        config_subdir = target_dir / "config"
        projects_yaml_path = config_subdir / "projects.yaml"
        agents_yaml_path = config_subdir / "agents.yaml"
    else:
        env_path = target_dir / ".env"
        projects_yaml_path = target_dir / "projects.yaml"
        agents_yaml_path = target_dir / "agents.yaml"
        config_subdir = None

    # Create directory structure
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        if config_subdir:
            config_subdir.mkdir(parents=True, exist_ok=True)
        print(f"\nCreating configuration in: {target_dir}")
    except Exception as e:
        print(f"Error: Failed to create config directory: {e}")
        return 1

    # Download agents.yaml from GitHub (with fallback)
    try:
        download_agents_yaml(agents_yaml_path)
    except Exception as e:
        print(f"Error: Failed to create agents.yaml: {e}")
        return 1

    # Generate .env file
    try:
        print("Writing .env...")
        generate_env_file(env_path, config)
    except Exception as e:
        print(f"Error: Failed to create .env: {e}")
        return 1

    # Generate projects.yaml file
    try:
        print("Writing projects.yaml...")
        generate_projects_yaml(projects_yaml_path, config)
    except Exception as e:
        print(f"Error: Failed to create projects.yaml: {e}")
        return 1

    # Success message
    print("\n" + "=" * 60)
    print("Success! Configuration created at:")
    print(f"  {target_dir}")
    print("=" * 60)

    # If dev mode, sync to ~/.remote-coder
    if is_dev_mode and project_root:
        sync_to_home_config(project_root)

    print("\nNext steps:")
    print("  1. Review your configuration files if needed")
    print("  2. Ensure your coding agent CLIs are installed and authenticated:")
    for agent in set(proj.default_agent for proj in config.projects):
        print(f"     - {agent}")
    print("  3. Invite your Slack bot to the project channels")
    print("  4. Start the daemon:")
    print("     remote-coder")
    print()

    return 0
