"""Agent configuration management command."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from ..core.config import resolve_config_dir


def run_config_agents_command(args) -> int:
    """Manage which agents are enabled in REMOTE_CODER_AGENTS."""

    # 1. Resolve config directory (always ~/.remote-coder)
    try:
        config_dir = resolve_config_dir(None)
    except Exception as e:
        print(f"Error: {e}")
        return 1

    env_file = config_dir / ".env"
    agents_file = config_dir / "agents.yaml"

    # 2. Check files exist
    if not env_file.exists():
        print(f"Error: .env not found at {env_file}")
        print(f"Run 'remote-coder init' first to create configuration.")
        return 1

    if not agents_file.exists():
        print(f"Error: agents.yaml not found at {agents_file}")
        return 1

    # 3. Load agents.yaml to get available agents
    available_agents = load_available_agents(agents_file)
    if not available_agents:
        print(f"Error: No agents defined in {agents_file}")
        return 1

    # 4. Load current selection from .env
    current_selection = load_current_agents_from_env(env_file)

    # 5. Check which CLIs are installed
    cli_status = check_cli_installations(available_agents)

    # 6. Show current state
    print_agent_status(available_agents, current_selection, cli_status)

    # 7. Prompt for new selection
    new_selection = prompt_agent_selection(available_agents, current_selection, cli_status)

    # 8. Update .env file
    update_env_agents(env_file, new_selection)

    print(f"\nUpdated! Agent configuration saved to {env_file}")
    print(f"Restart 'remote-coder' for changes to take effect.")

    return 0


def load_available_agents(agents_file: Path) -> list[str]:
    """Load list of agent names from agents.yaml."""
    try:
        data = yaml.safe_load(agents_file.read_text(encoding="utf-8"))
        return list(data.get("agents", {}).keys())
    except Exception as e:
        print(f"Error loading agents.yaml: {e}")
        return []


def load_current_agents_from_env(env_file: Path) -> list[str] | None:
    """
    Load REMOTE_CODER_AGENTS from .env.

    Returns:
        list[str] - Enabled agents
        None - Variable not set (means all agents enabled)
    """
    try:
        content = env_file.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error reading .env: {e}")
        return None

    # Look for REMOTE_CODER_AGENTS=...
    for line in content.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("REMOTE_CODER_AGENTS="):
            value = line_stripped.split("=", 1)[1].strip()
            if not value or value.startswith("#"):
                return None  # Commented out or empty
            return [a.strip() for a in value.split(",") if a.strip()]
        elif line_stripped.startswith("# REMOTE_CODER_AGENTS="):
            return None  # Commented out

    return None  # Not found in file


def check_cli_installations(agents: list[str]) -> dict[str, bool]:
    """Check which agent CLIs are installed."""
    return {agent: shutil.which(agent) is not None for agent in agents}


def print_agent_status(
    available: list[str],
    current: list[str] | None,
    cli_status: dict[str, bool]
) -> None:
    """Display current agent configuration."""
    print("\nAgent Configuration")
    print("=" * 60)

    if current is None:
        print("Current setting: All agents enabled (REMOTE_CODER_AGENTS not set)")
    else:
        print(f"Current setting: {', '.join(current) if current else 'None'}")

    print("\nAvailable agents:")
    for agent in available:
        enabled = "✓" if current is None or agent in current else "✗"
        cli_installed = "✓" if cli_status.get(agent) else "✗"
        print(f"  [{enabled}] {agent} (CLI installed: {cli_installed})")

    print()


def prompt_agent_selection(
    available: list[str],
    current: list[str] | None,
    cli_status: dict[str, bool]
) -> list[str]:
    """
    Prompt user to select which agents to enable.

    Simple text-based selection:
    - Show numbered list
    - User enters agent names (comma-separated)
    - Empty input = enable all
    """
    print("Select agents to enable:")
    print("  Enter agent names (comma-separated), e.g.: claude,codex")
    print("  Or press Enter to enable all agents")
    print()

    # Show options with numbers
    for i, agent in enumerate(available, 1):
        currently = "✓" if current is None or (current and agent in current) else " "
        cli = "✓" if cli_status.get(agent) else "✗"
        print(f"  {i}. [{currently}] {agent} (CLI: {cli})")

    while True:
        try:
            user_input = input("\nYour selection: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            raise SystemExit(0)

        # Empty = all agents
        if not user_input:
            print("Enabling all agents")
            return []  # Empty list means "all agents"

        # Parse input
        selected = []
        for part in user_input.split(","):
            part = part.strip().lower()
            if part in available:
                selected.append(part)
            else:
                print(f"Warning: Unknown agent '{part}', skipping")

        if not selected:
            confirm = input("No agents selected. Continue? (y/N): ")
            if confirm.lower() != 'y':
                continue

        # Warn about CLIs not installed
        not_installed = [a for a in selected if not cli_status.get(a)]
        if not_installed:
            print(f"\nWarning: CLIs not installed for: {', '.join(not_installed)}")
            confirm = input("Continue anyway? (y/N): ")
            if confirm.lower() != 'y':
                continue

        return selected


def update_env_agents(env_file: Path, agents: list[str]) -> None:
    """
    Update REMOTE_CODER_AGENTS in .env file.

    Args:
        agents: List of agent names, or empty list to enable all
    """
    try:
        content = env_file.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error reading .env: {e}")
        raise SystemExit(1)

    lines = content.splitlines()

    # Find and update the line
    updated = False
    new_lines = []

    for line in lines:
        line_stripped = line.strip()
        if line_stripped.startswith("REMOTE_CODER_AGENTS=") or \
           line_stripped.startswith("# REMOTE_CODER_AGENTS="):
            # Replace this line
            if agents:
                new_line = f"REMOTE_CODER_AGENTS={','.join(agents)}"
            else:
                new_line = "# REMOTE_CODER_AGENTS=  # Empty = all agents enabled"
            new_lines.append(new_line)
            updated = True
        else:
            new_lines.append(line)

    # If not found, add it
    if not updated:
        # Find the agent filtering section or end of file
        inserted = False
        for i, line in enumerate(new_lines):
            if "Agent filtering" in line or "agent" in line.lower():
                if agents:
                    new_lines.insert(i + 1, f"REMOTE_CODER_AGENTS={','.join(agents)}")
                else:
                    new_lines.insert(i + 1, "# REMOTE_CODER_AGENTS=  # Empty = all agents enabled")
                inserted = True
                break

        if not inserted:
            # Append at end
            new_lines.append("")
            new_lines.append("# Agent filtering")
            if agents:
                new_lines.append(f"REMOTE_CODER_AGENTS={','.join(agents)}")
            else:
                new_lines.append("# REMOTE_CODER_AGENTS=  # Empty = all agents enabled")

    # Write back
    try:
        env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    except Exception as e:
        print(f"Error writing .env: {e}")
        raise SystemExit(1)
