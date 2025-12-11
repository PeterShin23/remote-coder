"""Shared utilities for CLI commands."""

from __future__ import annotations

import subprocess
from pathlib import Path

DEFAULT_CONFIG_DIR = Path("~/.remote-coder").expanduser()


def detect_dev_mode() -> tuple[bool, Path | None]:
    """
    Check if running from within the remote-coder project directory.

    Walks up from current working directory looking for pyproject.toml
    that contains 'name = "remote-coder"'.

    Returns:
        (is_dev_mode, project_root) - project_root is None if not in dev mode
    """
    try:
        cwd = Path.cwd().resolve()
    except OSError:
        return False, None

    # Walk up the directory tree
    current = cwd
    for _ in range(10):  # Limit depth to avoid infinite loops
        pyproject = current / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8")
                # Simple check for project name
                if 'name = "remote-coder"' in content or "name = 'remote-coder'" in content:
                    # Verify it's actually the project (has expected structure)
                    if (current / "src" / "commands").exists():
                        return True, current
            except (OSError, UnicodeDecodeError):
                pass

        parent = current.parent
        if parent == current:  # Reached root
            break
        current = parent

    return False, None


def get_env_file_path() -> tuple[Path, bool, Path | None]:
    """
    Get the appropriate .env file path based on dev/user mode.

    Returns:
        (env_file_path, is_dev_mode, project_root)
    """
    is_dev, project_root = detect_dev_mode()

    if is_dev and project_root:
        return project_root / ".env", True, project_root
    else:
        return DEFAULT_CONFIG_DIR / ".env", False, None


def sync_to_home_config(project_root: Path) -> bool:
    """
    Sync project config to ~/.remote-coder/ with overwrite confirmation.

    Runs the copy_configs.sh script from the project root.

    Args:
        project_root: Path to the remote-coder project root

    Returns:
        True if synced successfully, False if user declined or error occurred
    """
    home_env = DEFAULT_CONFIG_DIR / ".env"

    # Check if we need to confirm overwrite
    if home_env.exists():
        try:
            response = input(f"\n{home_env} already exists. Overwrite? (Y/n): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nSync cancelled.")
            return False

        if response == "n":
            print(f"Skipped sync. Run './scripts/copy_configs.sh' manually when ready.")
            return False

    # Run copy_configs.sh
    script_path = project_root / "scripts" / "copy_configs.sh"

    if not script_path.exists():
        print(f"Warning: {script_path} not found. Cannot sync automatically.")
        print(f"Please manually copy your config to {DEFAULT_CONFIG_DIR}")
        return False

    print(f"→ Syncing to {DEFAULT_CONFIG_DIR}...")

    try:
        result = subprocess.run(
            ["bash", str(script_path)],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            print(f"✓ Configuration synced to {DEFAULT_CONFIG_DIR}")
            return True
        else:
            print(f"⚠ Sync failed: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print("⚠ Sync timed out")
        return False
    except Exception as e:
        print(f"⚠ Sync error: {e}")
        return False
