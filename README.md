# Remote Coder (Python)

Remote Coder is a Slack-first daemon that lets you control local coding agents, stream their output into Slack threads, and eventually sync progress back to GitHub pull requests. The project runs entirely on your machine, using the official Slack SDK (Socket Mode) and PyGithub.

## Getting Started

> Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/getting-started/installation/), Slack workspace admin access (to create an app), and a GitHub account.

1. **Clone & enter the repo**

   ```bash
   git clone https://github.com/PeterShin23/remote-coder.git
   cd remote-coder
   ```

2. **Copy env + config templates**

   ```bash
   cp .env.example .env
   cp config/projects.yaml.example config/projects.yaml  # create if missing
   ```

3. **Create a Slack App**

   - Visit [api.slack.com/apps](https://api.slack.com/apps), create an app, and enable **Socket Mode**.
   - Example Manifest

   ```json
   {
     "display_information": {
       "name": "Remote Coder"
     },
     "settings": {
       "org_deploy_enabled": false,
       "socket_mode_enabled": true,
       "is_hosted": false,
       "token_rotation_enabled": false
     }
   }
   ```

   - Add scopes your bot needs (minimum: `app_mentions:read`, `channels:history`, `channels:read`, `chat:write`; add `message.channels` if you want to capture every message in a channel without @-mentions).
   - Under **Event Subscriptions**, turn it on, choose Socket Mode delivery, and subscribe to:
     - `app_mention` (always required so mentions work).
     - `message.channels` if you want to react to all channel traffic.
     - Reinstall the app after adding scopes/events so Slack issues a token that matches the new permissions.
   - Install (or reinstall) the app to your workspace and copy:
     - **Bot User OAuth Token** (`SLACK_BOT_TOKEN`, looks like `xoxb-...`)
     - **App-Level Token** (`SLACK_APP_TOKEN`, looks like `xapp-1-...`)
   - Set `SLACK_ALLOWED_USER_ID` to your Slack user ID (find it in your Slack profile menu).

4. **Create a GitHub token (optional for PR features)**

   - Generate a PAT with `repo` + `pull_request` scopes at [github.com/settings/tokens](https://github.com/settings/tokens).
   - Add it to `.env` as `GITHUB_TOKEN=ghp_...`.

5. **Install dependencies with uv**

   ```bash
   uv pip install -e .
   ```

   Note: May ask to create virtual environment first

   ```bash
   uv venv
   ```

6. **Configure your projects**

   - Edit `config/projects.yaml` to map Slack channels to local paths/agents (the `default_agent` must match one of your agents).
   - Edit `config/agents.yaml` to list the one-shot agent commands. Each entry looks like:
     ```yaml
     agents:
       claude:
         type: claude # supported: claude, codex (gemini coming soon)
         command: ["claude", "--print", "--permission-mode", "acceptEdits", ...]
         working_dir_mode: project
         env:
           CLAUDE_API_KEY: "..."
     ```
     Commands run once per Slack message, so make sure the CLI you specify supports non-interactive `--print` / exec style usage.

7. **Run the daemon**
   ```bash
   uv run python -m src
   ```
   You should see log lines confirming the Slack Socket Mode connection. Mention or DM the bot (from the allowed user) to verify you see logging output.
   - Built-in Slack thread commands (either `!command` or `@remote-coder command`):
     - `!switch <agent-id>` / `@remote-coder use <agent-id>` – switch the current session to another configured agent.
     - `!status` / `@remote-coder status` – display the active agent and message history count.
     - `!end` / `@remote-coder end` – end the current session (start a new Slack thread to reset state).

## Useful Links

- Slack Socket Mode Docs: <https://api.slack.com/apis/connections/socket>
- Slack App Management: <https://api.slack.com/apps>
- PyGithub: <https://pygithub.readthedocs.io/>
- uv Tooling: <https://docs.astral.sh/uv/>

## Roadmap

Implementation follows `plans/1-implementation.md`. Passes 1–2 (Python skeleton and Slack adapter) are in place; upcoming work focuses on agent process management, command handling, GitHub integration, and polishing for production use.
