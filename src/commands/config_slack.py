"""Slack configuration command with guided setup flow."""

from __future__ import annotations

import json
import urllib.parse
import webbrowser
from pathlib import Path

from .utils import DEFAULT_CONFIG_DIR, get_env_file_path, sync_to_home_config
from .validators import validate_slack_app_token, validate_slack_bot_token, validate_slack_user_ids

# Slack App Manifest - pre-configures all required settings
SLACK_APP_MANIFEST = {
    "display_information": {
        "name": "Remote Coder",
        "description": "Control local coding agents through Slack",
        "background_color": "#1a1a2e",
    },
    "features": {
        "bot_user": {
            "display_name": "Remote Coder",
            "always_online": True,
        },
    },
    "oauth_config": {
        "scopes": {
            "bot": [
                "app_mentions:read",
                "channels:history",
                "channels:read",
                "chat:write",
            ],
        },
    },
    "settings": {
        "event_subscriptions": {
            "bot_events": [
                "app_mention",
                "message.channels",
            ],
        },
        "interactivity": {
            "is_enabled": False,
        },
        "org_deploy_enabled": False,
        "socket_mode_enabled": True,
        "token_rotation_enabled": False,
    },
}


def validate_slack_bot_token_api(token: str) -> tuple[bool, str, dict | None]:
    """
    Validate Slack bot token by calling auth.test API.

    Returns:
        (is_valid, error_message, response_data)
    """
    try:
        import urllib.request

        req = urllib.request.Request(
            "https://slack.com/api/auth.test",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())

        if data.get("ok"):
            return True, "", data
        else:
            return False, data.get("error", "Unknown error"), None
    except Exception as e:
        return False, f"API request failed: {e}", None


def validate_slack_app_token_api(token: str) -> tuple[bool, str]:
    """
    Validate Slack app token by attempting a connections.open call.

    Note: We can't fully test without actually connecting, so we do a basic
    format check and trust the user. Real validation happens at runtime.
    """
    # App tokens can't be easily validated without establishing a socket connection
    # We'll do format validation and trust the user
    is_valid, error = validate_slack_app_token(token)
    if not is_valid:
        return False, error
    return True, ""


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


def open_browser_with_prompt(url: str, description: str) -> bool:
    """Open browser and wait for user confirmation."""
    print(f"\n→ Opening browser: {description}")
    print(f"  URL: {url}")

    try:
        webbrowser.open(url)
        print("  (Browser opened automatically)")
    except Exception:
        print("  (Could not open browser automatically - please open the URL manually)")

    input("\nPress Enter when ready to continue...")
    return True


def run_config_slack_command(args) -> int:
    """Guide user through Slack app setup."""

    print("\n" + "=" * 60)
    print("Slack Configuration")
    print("=" * 60)

    # Detect dev mode and get appropriate paths
    env_file, is_dev_mode, project_root = get_env_file_path()
    env_exists = env_file.exists()

    if is_dev_mode:
        print(f"\n[Dev mode detected - will update {env_file}]")
    elif env_exists:
        print(f"\nExisting configuration found at: {env_file.parent}")
        print("This will update your Slack credentials.\n")
    else:
        print(f"\nConfiguration will be saved to: {env_file.parent}")
        print("Note: Run 'remote-coder init' for full setup including projects.\n")

    # Ask if user has existing Slack app
    print("Do you have an existing Slack app configured for Remote Coder?")
    has_app = input("(y/N): ").strip().lower()

    if has_app != "y":
        # Guide through app creation with manifest
        print("\n" + "-" * 60)
        print("Step 1: Create Slack App from Manifest")
        print("-" * 60)
        print("\nWe'll create a Slack app with all the required settings pre-configured.")
        print("This includes:")
        print("  • Socket Mode enabled")
        print("  • Bot scopes: app_mentions:read, channels:history, channels:read, chat:write")
        print("  • Event subscriptions: app_mention, message.channels")

        # Create manifest URL
        manifest_json = json.dumps(SLACK_APP_MANIFEST)
        manifest_encoded = urllib.parse.quote(manifest_json)
        create_app_url = f"https://api.slack.com/apps?new_app=1&manifest_json={manifest_encoded}"

        input("\nPress Enter to open Slack's app creation page...")

        try:
            webbrowser.open(create_app_url)
            print("\n✓ Browser opened to Slack app creation page")
        except Exception:
            print("\n⚠ Could not open browser automatically.")
            print(f"Please visit: https://api.slack.com/apps")
            print("\nThen create a new app and paste this manifest:")
            print("-" * 40)
            print(json.dumps(SLACK_APP_MANIFEST, indent=2))
            print("-" * 40)

        print("\nIn the browser:")
        print("  1. Select your workspace")
        print("  2. Review the app configuration")
        print("  3. Click 'Create'")

        input("\nPress Enter after creating the app...")

    # Step 2: Generate App-Level Token
    print("\n" + "-" * 60)
    print("Step 2: Generate App-Level Token")
    print("-" * 60)
    print("\nThe App-Level Token enables Socket Mode for real-time communication.")

    open_browser_with_prompt(
        "https://api.slack.com/apps",
        "Slack App Settings"
    )

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

    # Validate app token format
    is_valid, error = validate_slack_app_token_api(slack_app_token)
    if is_valid:
        print("✓ App token format valid")
    else:
        print(f"⚠ Warning: {error}")

    # Step 3: Install App & Get Bot Token
    print("\n" + "-" * 60)
    print("Step 3: Install App & Get Bot Token")
    print("-" * 60)

    print("\nNow we need to install the app to your workspace to get the Bot Token.")
    print("\nIn your app settings:")
    print("  1. Go to 'OAuth & Permissions' in the left sidebar")
    print("  2. Click 'Install to Workspace' (or 'Reinstall' if already installed)")
    print("  3. Authorize the app")
    print("  4. Copy the 'Bot User OAuth Token' (starts with xoxb-)")

    slack_bot_token = prompt_with_validation(
        "\nPaste your Bot User OAuth Token (xoxb-...)",
        validate_slack_bot_token,
        required=True,
    )

    # Validate bot token with API call
    print("\n→ Validating bot token...")
    is_valid, error, auth_data = validate_slack_bot_token_api(slack_bot_token)

    if is_valid and auth_data:
        print(f"✓ Bot token valid!")
        print(f"  Team: {auth_data.get('team', 'Unknown')}")
        print(f"  Bot: {auth_data.get('user', 'Unknown')}")
        bot_user_id = auth_data.get("user_id", "")
    else:
        print(f"⚠ Warning: Could not validate token - {error}")
        print("  The token may still work. Continuing...")
        bot_user_id = ""

    # Step 4: Get User IDs
    print("\n" + "-" * 60)
    print("Step 4: Configure Allowed Users")
    print("-" * 60)

    print("\nRemote Coder only responds to messages from allowed users.")
    print("\nTo find your Slack User ID:")
    print("  1. Click on your profile picture in Slack")
    print("  2. Click 'Profile'")
    print("  3. Click the '...' menu")
    print("  4. Select 'Copy member ID'")

    if bot_user_id:
        print(f"\n(Note: The bot's user ID is {bot_user_id} - don't add this one)")

    slack_user_ids = prompt_with_validation(
        "\nEnter allowed Slack user IDs (comma-separated, e.g., U01ABC123,U02DEF456)",
        validate_slack_user_ids,
        required=True,
    )

    # Summary
    print("\n" + "=" * 60)
    print("Configuration Summary")
    print("=" * 60)
    print(f"\nSlack App Token: {slack_app_token[:15]}...{slack_app_token[-4:]}")
    print(f"Slack Bot Token: {slack_bot_token[:15]}...{slack_bot_token[-4:]}")
    print(f"Allowed Users: {slack_user_ids}")

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
    update_env_slack_config(env_file, slack_bot_token, slack_app_token, slack_user_ids)

    print(f"\n✓ Slack configuration saved to {env_file}")

    # If dev mode, sync to ~/.remote-coder
    if is_dev_mode and project_root:
        sync_to_home_config(project_root)

    print("\nNext steps:")
    print("  1. Invite your bot to the channels it should monitor")
    print("  2. Run 'remote-coder init' if you haven't set up projects yet")
    print("  3. Or run 'remote-coder' to start the daemon")

    return 0


def update_env_slack_config(
    env_file: Path,
    bot_token: str,
    app_token: str,
    user_ids: str,
) -> None:
    """Update or create Slack configuration in .env file."""

    if env_file.exists():
        content = env_file.read_text(encoding="utf-8")
        lines = content.splitlines()
    else:
        lines = [
            "# Remote Coder Configuration",
            "# Generated by remote-coder config slack",
            "",
            "# Slack Configuration",
        ]

    # Update or add each Slack variable
    slack_vars = {
        "SLACK_BOT_TOKEN": bot_token,
        "SLACK_APP_TOKEN": app_token,
        "SLACK_ALLOWED_USER_IDS": user_ids,
    }

    for var_name, var_value in slack_vars.items():
        updated = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{var_name}=") or stripped.startswith(f"# {var_name}="):
                lines[i] = f"{var_name}={var_value}"
                updated = True
                break

        if not updated:
            # Find Slack Configuration section or add at appropriate place
            inserted = False
            for i, line in enumerate(lines):
                if "Slack Configuration" in line:
                    # Insert after the section header
                    insert_idx = i + 1
                    while insert_idx < len(lines) and lines[insert_idx].strip().startswith(("SLACK_", "# SLACK_")):
                        insert_idx += 1
                    lines.insert(insert_idx, f"{var_name}={var_value}")
                    inserted = True
                    break

            if not inserted:
                # Add at end with section header
                if lines and lines[-1].strip():
                    lines.append("")
                lines.append("# Slack Configuration")
                lines.append(f"{var_name}={var_value}")

    # Write back
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env_file.chmod(0o600)
