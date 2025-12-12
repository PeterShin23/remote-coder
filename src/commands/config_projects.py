"""Project configuration management command."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from .utils import DEFAULT_CONFIG_DIR, detect_dev_mode, sync_to_home_config
from .validators import (
    validate_agent_name,
    validate_branch_name,
    validate_channel_name,
    validate_github_owner,
    validate_github_repo,
    validate_project_path,
)

# Available agents (should match agents.yaml)
AVAILABLE_AGENTS = ["claude", "codex", "gemini"]


def get_projects_yaml_path() -> tuple[Path, bool, Path | None]:
    """
    Get the projects.yaml path based on dev/user mode.

    Returns:
        (projects_yaml_path, is_dev_mode, project_root)
    """
    is_dev, project_root = detect_dev_mode()

    if is_dev and project_root:
        return project_root / "config" / "projects.yaml", True, project_root
    else:
        return DEFAULT_CONFIG_DIR / "projects.yaml", False, None


def load_projects_yaml(projects_file: Path) -> dict:
    """Load projects.yaml file."""
    if not projects_file.exists():
        print(f"Error: {projects_file} not found")
        print("Run 'remote-coder init' first to create configuration.")
        raise SystemExit(1)

    try:
        with projects_file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if data else {"base_dir": "", "projects": {}}
    except Exception as e:
        print(f"Error loading {projects_file}: {e}")
        raise SystemExit(1)


def save_projects_yaml(projects_file: Path, data: dict) -> None:
    """Save projects.yaml file."""
    try:
        with projects_file.open("w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        projects_file.chmod(0o600)
    except Exception as e:
        print(f"Error saving {projects_file}: {e}")
        raise SystemExit(1)


def validate_project_directory(base_dir: Path, relative_path: str) -> tuple[bool, str]:
    """
    Validate that project directory exists and is a proper git repo.

    Returns:
        (is_valid, error_message)
    """
    full_path = (base_dir / relative_path).resolve()

    # Check exists
    if not full_path.exists():
        return False, f"Directory does not exist: {full_path}"

    # Check is directory
    if not full_path.is_dir():
        return False, f"Path is not a directory: {full_path}"

    # Check is git repo
    git_dir = full_path / ".git"
    if not git_dir.exists():
        return False, f"Not a git repository: {full_path}"

    # Check has remote configured
    try:
        result = subprocess.run(
            ["git", "-C", str(full_path), "remote", "-v"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False, f"No git remote configured in: {full_path}"
    except Exception as e:
        return False, f"Error checking git remote: {e}"

    return True, ""


def prompt_with_validation(prompt_text: str, validator, required: bool = True, default: str | None = None) -> str:
    """Prompt user for input with validation."""
    if default:
        prompt_text = f"{prompt_text} [{default}]"
    prompt_text = f"{prompt_text}: "

    while True:
        try:
            user_input = input(prompt_text).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            raise SystemExit(0)

        # Use default if provided and user pressed Enter
        if not user_input and default:
            user_input = default

        if required and not user_input:
            print("Error: This field is required.\n")
            continue

        if not required and not user_input:
            return user_input

        is_valid, error_msg = validator(user_input)
        if is_valid:
            return user_input
        else:
            print(f"Error: {error_msg}\n")


def add_project() -> int:
    """Interactive flow to add a new project."""
    projects_file, is_dev_mode, project_root = get_projects_yaml_path()

    if is_dev_mode:
        print(f"\n[Dev mode detected - will update {projects_file}]")

    print("\n" + "=" * 60)
    print("Adding new project to Remote Coder")
    print("=" * 60)

    # Load existing config
    data = load_projects_yaml(projects_file)
    base_dir = Path(data.get("base_dir", "")).expanduser().resolve()

    if not base_dir or not base_dir.exists():
        print(f"\nError: Base directory not configured or doesn't exist: {base_dir}")
        print("Run 'remote-coder init' to set up base directory.")
        return 1

    print(f"\nBase directory: {base_dir}")

    # Get channel name
    print("\nStep 1: Slack Channel")
    print("-" * 60)
    channel_name = prompt_with_validation(
        "Enter Slack channel name",
        validate_channel_name,
        required=True,
    )

    # Check if channel already exists
    if channel_name in data.get("projects", {}):
        print(f"\nError: Project '{channel_name}' already exists.")
        print("Use 'remote-coder config projects edit' to modify it.")
        return 1

    # Get project path
    print("\nStep 2: Project Path")
    print("-" * 60)
    print(f"Enter path relative to {base_dir}")
    print(f"Example: If your project is at {base_dir}/my-app, enter: my-app")

    while True:
        project_path = prompt_with_validation(
            "Project path",
            validate_project_path,
            required=True,
        )

        # Validate directory exists and is git repo
        is_valid, error = validate_project_directory(base_dir, project_path)
        if is_valid:
            break
        else:
            print(f"Error: {error}\n")
            retry = input("Try again? (Y/n): ").strip().lower()
            if retry == "n":
                return 0

    # Get default agent
    print("\nStep 3: Default Agent")
    print("-" * 60)
    default_agent = prompt_with_validation(
        f"Select default agent ({'/'.join(AVAILABLE_AGENTS)})",
        lambda x: validate_agent_name(x, AVAILABLE_AGENTS),
        required=True,
    )

    # GitHub info (optional)
    print("\nStep 4: GitHub Integration (Optional)")
    print("-" * 60)
    print("Press Enter to skip GitHub integration")

    github_owner = prompt_with_validation(
        "Enter GitHub owner/organization",
        validate_github_owner,
        required=False,
    )

    github_repo = None
    default_base_branch = "main"

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

    # Summary
    print("\n" + "=" * 60)
    print("Configuration Summary")
    print("=" * 60)
    print(f"\nChannel: #{channel_name}")
    print(f"Path: {base_dir}/{project_path}")
    print(f"Agent: {default_agent}")
    if github_owner and github_repo:
        print(f"GitHub: {github_owner}/{github_repo} ({default_base_branch})")
    else:
        print("GitHub: Not configured")

    # Confirm
    try:
        confirm = input("\nAdd this project? (Y/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return 0

    if confirm == "n":
        print("Cancelled.")
        return 0

    # Add project to data
    project_data = {
        "path": project_path,
        "default_agent": default_agent,
    }

    if github_owner and github_repo:
        project_data["github"] = {
            "owner": github_owner,
            "repo": github_repo,
            "default_base_branch": default_base_branch,
        }

    if "projects" not in data:
        data["projects"] = {}

    data["projects"][channel_name] = project_data

    # Save
    save_projects_yaml(projects_file, data)

    print(f"\n✓ Project added to {projects_file}")

    # If dev mode, sync to ~/.remote-coder
    if is_dev_mode and project_root:
        sync_to_home_config(project_root)

    print("\nNext steps:")
    print(f"  1. Invite your Slack bot to #{channel_name}")
    print("  2. Restart the daemon or use !reload-projects in Slack")

    return 0


def list_projects() -> int:
    """Display all configured projects."""
    projects_file, is_dev_mode, _ = get_projects_yaml_path()

    print("\n" + "=" * 60)
    print(f"Projects in {projects_file}")
    print("=" * 60)

    # Load config
    data = load_projects_yaml(projects_file)
    base_dir = data.get("base_dir", "")
    projects = data.get("projects", {})

    print(f"\nBase directory: {base_dir}")

    if not projects:
        print("\nNo projects configured.")
        print("Run 'remote-coder config projects add' to add one.")
        return 0

    print(f"\nConfigured projects ({len(projects)}):\n")

    for i, (channel, project_data) in enumerate(projects.items(), 1):
        path = project_data.get("path", "")
        agent = project_data.get("default_agent", "")
        github = project_data.get("github", {})

        print(f"{i}. {channel}")
        print(f"   Path: {path}")
        print(f"   Default Agent: {agent}")

        if github:
            owner = github.get("owner", "")
            repo = github.get("repo", "")
            branch = github.get("default_base_branch", "main")
            print(f"   GitHub: {owner}/{repo} ({branch})")
        else:
            print(f"   GitHub: Not configured")
        print()
    
    print("The following commands can be appended:\n")
    print(f"   add (to add to the list of configured projects)")
    print(f"   edit (to edit a configured project)")
    print(f"   remove (to remove a configured project)")

    return 0


def remove_project() -> int:
    """Interactive flow to remove a project."""
    projects_file, is_dev_mode, project_root = get_projects_yaml_path()

    if is_dev_mode:
        print(f"\n[Dev mode detected - will update {projects_file}]")

    print("\n" + "=" * 60)
    print("Remove Project")
    print("=" * 60)

    # Load config
    data = load_projects_yaml(projects_file)
    projects = data.get("projects", {})

    if not projects:
        print("\nNo projects configured.")
        return 0

    # Show list
    print("\nSelect project to remove:\n")
    project_list = list(projects.items())

    for i, (channel, project_data) in enumerate(project_list, 1):
        path = project_data.get("path", "")
        print(f"  [{i}] {channel} ({path})")

    # Get selection
    while True:
        try:
            choice = input(f"\nYour choice (1-{len(project_list)}) or 'q' to quit: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return 0

        if choice.lower() == "q":
            print("Cancelled.")
            return 0

        try:
            index = int(choice) - 1
            if 0 <= index < len(project_list):
                channel_name = project_list[index][0]
                break
            else:
                print(f"Error: Please enter a number between 1 and {len(project_list)}")
        except ValueError:
            print("Error: Invalid input")

    # Confirm removal
    try:
        confirm = input(f"\nRemove '{channel_name}'? (y/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return 0

    if confirm != "y":
        print("Cancelled.")
        return 0

    # Remove from data
    del data["projects"][channel_name]

    # Save
    save_projects_yaml(projects_file, data)

    print(f"\n✓ Project '{channel_name}' removed from {projects_file}")

    # If dev mode, sync to ~/.remote-coder
    if is_dev_mode and project_root:
        sync_to_home_config(project_root)

    print("\nRestart the daemon or use !reload-projects in Slack")

    return 0


def edit_project() -> int:
    """Interactive flow to edit an existing project."""
    print("\nEdit project functionality coming soon!")
    print("For now, use 'remote-coder config projects remove' and 'add' to replace a project.")
    return 0


def run_config_projects_command(args) -> int:
    """Entry point for 'remote-coder config projects' command."""
    # Default to list if no subcommand
    command = getattr(args, "projects_command", None)

    if command == "add":
        return add_project()
    elif command == "remove":
        return remove_project()
    elif command == "edit":
        return edit_project()
    else:
        # Default: show list
        return list_projects()
