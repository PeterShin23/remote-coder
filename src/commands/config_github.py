"""GitHub configuration command with guided setup flow."""

from __future__ import annotations

import json
import webbrowser
from pathlib import Path

from .utils import DEFAULT_CONFIG_DIR, get_env_file_path, sync_to_home_config
from .validators import validate_github_token


def validate_github_token_api(token: str) -> tuple[bool, str, dict | None]:
    """
    Validate GitHub token by calling the user API.

    Returns:
        (is_valid, error_message, user_data)
    """
    try:
        import urllib.request

        req = urllib.request.Request(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "remote-coder",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())

        return True, "", data
    except urllib.request.HTTPError as e:
        if e.code == 401:
            return False, "Invalid or expired token", None
        elif e.code == 403:
            return False, "Token lacks required permissions", None
        else:
            return False, f"GitHub API error: {e.code}", None
    except Exception as e:
        return False, f"API request failed: {e}", None


def check_github_token_scopes(token: str) -> tuple[bool, list[str], str]:
    """
    Check what scopes/permissions the token has.

    Returns:
        (has_required_scopes, scopes_list, error_message)
    """
    try:
        import urllib.request

        req = urllib.request.Request(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "remote-coder",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            # Scopes are in the response headers for classic tokens
            scopes_header = response.headers.get("X-OAuth-Scopes", "")
            scopes = [s.strip() for s in scopes_header.split(",") if s.strip()]

            # Fine-grained tokens don't have X-OAuth-Scopes
            if not scopes:
                # Check if it's a fine-grained token (they work but don't expose scopes)
                return True, ["fine-grained-token"], ""

            # Check for required scopes
            has_repo = "repo" in scopes
            # repo scope includes all PR permissions
            if has_repo:
                return True, scopes, ""
            else:
                return False, scopes, "Token missing 'repo' scope needed for PR management"

    except Exception as e:
        return False, [], f"Could not check scopes: {e}"


def prompt_with_validation(
    prompt_text: str,
    validator,
    required: bool = True,
) -> str:
    """Prompt user for input with validation."""
    prompt_text = f"{prompt_text}: "

    while True:
        try:
            user_input = input(prompt_text).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSetup cancelled.")
            raise SystemExit(0)

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


def run_config_github_command(args) -> int:
    """Guide user through GitHub token setup."""

    print("\n" + "=" * 60)
    print("GitHub Configuration")
    print("=" * 60)

    # Detect dev mode and get appropriate paths
    env_file, is_dev_mode, project_root = get_env_file_path()
    env_exists = env_file.exists()

    if is_dev_mode:
        print(f"\n[Dev mode detected - will update {env_file}]")
    elif env_exists:
        print(f"\nExisting configuration found at: {env_file.parent}")
        print("This will update your GitHub token.\n")
    else:
        print(f"\nConfiguration will be saved to: {env_file.parent}")
        print("Note: Run 'remote-coder init' for full setup including projects.\n")

    print("GitHub integration enables Remote Coder to:")
    print("  • Automatically create and update pull requests")
    print("  • Sync PR review comments back to Slack")
    print("  • Manage branches for each session")

    # Ask if they want to set up GitHub
    print("\nWould you like to configure GitHub integration?")
    setup_github = input("(Y/n): ").strip().lower()

    if setup_github == "n":
        print("\nSkipping GitHub setup. You can run this command later to add it.")
        return 0

    # Check if they have an existing token
    print("\n" + "-" * 60)
    print("GitHub Personal Access Token Setup")
    print("-" * 60)

    print("\nDo you have an existing GitHub Personal Access Token?")
    has_token = input("(y/N): ").strip().lower()

    if has_token != "y":
        # Guide through token creation
        print("\n" + "-" * 60)
        print("Step 1: Create Personal Access Token")
        print("-" * 60)

        print("\nYou can create either:")
        print("  1. Fine-grained token (recommended) - scoped to specific repos")
        print("  2. Classic token - broader access")

        print("\nWhich type would you like to create?")
        print("  [1] Fine-grained token (recommended)")
        print("  [2] Classic token")

        token_type = input("\nYour choice (1/2): ").strip()

        if token_type == "2":
            # Classic token
            classic_url = "https://github.com/settings/tokens/new?description=Remote%20Coder&scopes=repo"

            print("\nOpening GitHub to create a classic token...")
            print("\nRequired scope: 'repo' (Full control of private repositories)")
            print("This includes read/write access to code, PRs, issues, etc.")

            input("\nPress Enter to open browser...")

            try:
                webbrowser.open(classic_url)
                print("✓ Browser opened")
            except Exception:
                print(f"⚠ Could not open browser. Please visit:")
                print(f"  {classic_url}")

            print("\nIn the browser:")
            print("  1. Verify 'repo' scope is checked")
            print("  2. Set an expiration (or 'No expiration')")
            print("  3. Click 'Generate token'")
            print("  4. Copy the token (starts with ghp_)")

        else:
            # Fine-grained token (default)
            fine_grained_url = "https://github.com/settings/personal-access-tokens/new"

            print("\nOpening GitHub to create a fine-grained token...")
            print("\nYou'll need to configure:")
            print("  • Token name: e.g., 'Remote Coder'")
            print("  • Expiration: your choice")
            print("  • Repository access: select repos Remote Coder will manage")
            print("  • Permissions:")
            print("    - Contents: Read and write")
            print("    - Pull requests: Read and write")
            print("    - Metadata: Read (usually auto-selected)")

            input("\nPress Enter to open browser...")

            try:
                webbrowser.open(fine_grained_url)
                print("✓ Browser opened")
            except Exception:
                print(f"⚠ Could not open browser. Please visit:")
                print(f"  {fine_grained_url}")

            print("\nIn the browser:")
            print("  1. Set token name and expiration")
            print("  2. Under 'Repository access', select your repos")
            print("  3. Under 'Permissions' > 'Repository permissions':")
            print("     - Contents: Read and write")
            print("     - Pull requests: Read and write")
            print("  4. Click 'Generate token'")
            print("  5. Copy the token (starts with github_pat_)")

    # Get the token
    print("\n" + "-" * 60)
    print("Step 2: Enter Your Token")
    print("-" * 60)

    github_token = prompt_with_validation(
        "\nPaste your GitHub token",
        validate_github_token,
        required=True,
    )

    # Validate token with API
    print("\n→ Validating token...")
    is_valid, error, user_data = validate_github_token_api(github_token)

    if is_valid and user_data:
        print(f"✓ Token valid!")
        print(f"  Authenticated as: {user_data.get('login', 'Unknown')}")

        # Check scopes
        has_scopes, scopes, scope_error = check_github_token_scopes(github_token)
        if scopes:
            if "fine-grained-token" in scopes:
                print("  Token type: Fine-grained (permissions not shown)")
            else:
                print(f"  Scopes: {', '.join(scopes)}")

        if not has_scopes:
            print(f"\n⚠ Warning: {scope_error}")
            print("  The token may not have sufficient permissions for PR management.")
            continue_anyway = input("  Continue anyway? (y/N): ").strip().lower()
            if continue_anyway != "y":
                print("\nPlease create a new token with the required permissions.")
                return 1
    else:
        print(f"⚠ Warning: Could not validate token - {error}")
        continue_anyway = input("Continue anyway? (y/N): ").strip().lower()
        if continue_anyway != "y":
            return 1

    # Summary
    print("\n" + "=" * 60)
    print("Configuration Summary")
    print("=" * 60)
    print(f"\nGitHub Token: {github_token[:15]}...{github_token[-4:]}")
    if user_data:
        print(f"Authenticated as: {user_data.get('login', 'Unknown')}")

    # Confirm
    try:
        confirm = input("\nSave this configuration? (Y/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled.")
        return 0

    if confirm == "n":
        print("Configuration cancelled.")
        return 0

    # Save to .env
    env_file.parent.mkdir(parents=True, exist_ok=True)
    update_env_github_config(env_file, github_token)

    print(f"\n✓ GitHub configuration saved to {env_file}")

    # If dev mode, sync to ~/.remote-coder
    if is_dev_mode and project_root:
        sync_to_home_config(project_root)

    print("\nNext steps:")
    print("  1. Make sure your projects.yaml has GitHub metadata configured")
    print("  2. Run 'remote-coder init' if you haven't set up projects yet")
    print("  3. Or run 'remote-coder' to start the daemon")

    return 0


def update_env_github_config(env_file: Path, token: str) -> None:
    """Update or create GitHub configuration in .env file."""

    if env_file.exists():
        content = env_file.read_text(encoding="utf-8")
        lines = content.splitlines()
    else:
        lines = [
            "# Remote Coder Configuration",
            "# Generated by remote-coder config github",
            "",
        ]

    # Update or add GITHUB_TOKEN
    var_name = "GITHUB_TOKEN"
    updated = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{var_name}=") or stripped.startswith(f"# {var_name}="):
            lines[i] = f"{var_name}={token}"
            updated = True
            break

    if not updated:
        # Find GitHub Configuration section or add at appropriate place
        inserted = False
        for i, line in enumerate(lines):
            if "GitHub Configuration" in line:
                # Insert after the section header
                insert_idx = i + 1
                while insert_idx < len(lines) and lines[insert_idx].strip().startswith(("GITHUB_", "# GITHUB_")):
                    insert_idx += 1
                lines.insert(insert_idx, f"{var_name}={token}")
                inserted = True
                break

        if not inserted:
            # Add at end with section header
            if lines and lines[-1].strip():
                lines.append("")
            lines.append("# GitHub Configuration")
            lines.append(f"{var_name}={token}")

    # Write back
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env_file.chmod(0o600)
