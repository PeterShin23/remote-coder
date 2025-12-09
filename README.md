# Remote Coder

> **Status: Public Alpha (`v0.0.1-alpha.1`)**  
> This is an early alpha release. APIs, config formats, and behavior may change between versions. Expect breaking changes and rough edges.

Remote Coder is a Slack-first daemon that lets you control local coding agents, stream their output into Slack threads, and eventually sync progress back to GitHub pull requests. The project runs entirely on your own machine.

## Features

- **Slack-first control center** – Operate your daemon entirely through Slack. Send requests, monitor output, and manage sessions without leaving your workspace.
- **Channel-to-repository mapping** – Each Slack channel connects to a configured local repository, keeping project contexts organized.
- **Thread-based sessions** – Every Slack thread is an isolated session with its own state, enabling concurrent work on the same repository.
- **Automatic PR management** – Changes are committed, pushed, and linked to GitHub pull requests automatically. Updates flow back to Slack with PR links.
- **Multi-agent support** – Switch between coding agents (Claude, Codex, Gemini) mid-session with a single command. No need to restart.
- **Zero API key overhead** – Uses local coding agent CLI installations. No additional LLM API keys required beyond what your CLIs already use.

## 🚀 Quickstart (Alpha)

Remote Coder is designed to run on your own machine, with your own tokens, using a simple config directory and `.env` file.

### 1. Install the CLI (using uv)

Make sure you have [uv](https://github.com/astral-sh/uv) and Python 3.11+ installed, then:

```bash
uv tool install git+https://github.com/PeterShin23/remote-coder --upgrade
```

This installs a global `remote-coder` command. Want to contribute or modify the code? Clone the repo and run `uv pip install -e .` from the project root for an editable install.

### 2. Create a config directory

By default, Remote Coder looks for its config in `~/.remote-coder`:

```bash
mkdir -p ~/.remote-coder
cd ~/.remote-coder
```

### 3. Add your `.env` and YAML configs

If you have the repo cloned locally, copy the example files (or download them directly from the [latest release](https://github.com/PeterShin23/remote-coder/releases)):

```bash
# from inside the repo
./scripts/copy_configs.sh
```

This copies your current `.env`, `config/projects.yaml`, and `config/agents.yaml` into `~/.remote-coder`, falling back to the example files if needed. After editing the files, rerun the script and use `!reload-projects` in Slack to apply changes without restarting. You can also copy files manually if you prefer:

```bash
cp /path/to/remote-coder/.env.example .env
cp /path/to/remote-coder/config/projects.yaml.example projects.yaml
cp /path/to/remote-coder/config/agents.yaml agents.yaml
```

Then edit `.env` and fill in:

- `SLACK_APP_TOKEN`
- `SLACK_BOT_TOKEN`
- `SLACK_ALLOWED_USER_IDS` (comma-separated list of Slack user IDs allowed to use the bot)
- `GITHUB_TOKEN` (optional, for PR automation)
- `REMOTE_CODER_AGENTS` (optional, comma-separated list to limit which agents load)

> Need help creating the Slack tokens? See **Slack App Setup** below.  
> When you want to add/remove projects later, open `projects.yaml` in your editor and edit it directly—there’s no extra CLI ceremony.

Remote Coder loads variables from `.env` and the current shell. Shell environment variables take precedence.

### 4. Start the daemon

From your config directory:

```bash
remote-coder
# or keep your Mac awake while it runs:
caffeinate -i remote-coder
```

You should see logs indicating that `.env` and the YAML files were loaded, Slack Socket Mode connected, and the daemon is listening for events. Built-in Slack thread commands include `!use`, `!status`, `!review`, `!reload-projects`, `!setup`, `!end`, `!purge`, and `!help`.

If you ever need to run against a different folder (for example, you keep configs inside your repo), either pass `--config-dir /path/to/config` or set an environment variable:

```bash
export REMOTE_CODER_CONFIG_DIR="/Users/you/projects/remote-coder/config"
remote-coder
```

### Selecting which agents to enable

All agents are defined in `agents.yaml`. By default, **all** agents in that file are enabled.

You can limit which agents Remote Coder uses by setting the `REMOTE_CODER_AGENTS` environment variable (comma-separated list of agent names):

```env
REMOTE_CODER_AGENTS=claude,codex
```

Rules:

- If `REMOTE_CODER_AGENTS` is unset or empty, all agents from `agents.yaml` are enabled.
- If it is set, only the listed agents are loaded.
- If any name in `REMOTE_CODER_AGENTS` does not exist in `agents.yaml`, Remote Coder fails fast on startup with a clear error message.

Set this in your `.env` file or export it in your shell before running `remote-coder`.

## Slack App Setup

> Prerequisites: Slack workspace admin access (to create and install apps).

1. Visit [api.slack.com/apps](https://api.slack.com/apps), create an app, and enable **Socket Mode**.
2. Example manifest:

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

3. Add scopes your bot needs (minimum: `app_mentions:read`, `channels:history`, `channels:read`, `chat:write`; add `message.channels` if you want to capture every message in a channel without @-mentions). 
4. Under **Event Subscriptions**, turn it on, choose Socket Mode delivery, and subscribe to:
   - `app_mention` (always required so mentions work)
   - `message.channels` if you want to react to all channel traffic
   - Reinstall the app after adding scopes/events so Slack issues a token that matches the new permissions.
5. Install (or reinstall) the app to your workspace and copy:
   - **Bot User OAuth Token** (`SLACK_BOT_TOKEN`, looks like `xoxb-...`)
   - **App-Level Token** (`SLACK_APP_TOKEN`, looks like `xapp-1-...`)
6. Set `SLACK_ALLOWED_USER_IDS` (comma-separated) to the Slack user IDs that can talk to the bot. You can find your user ID in your Slack profile.

## GitHub token (optional for PR features)

Future phases let the bot open/refresh pull requests and sync comments. Those calls require a GitHub token with access to the repositories you map in `projects.yaml`.

1. Head to [github.com/settings/tokens](https://github.com/settings/tokens) and create either:
   - A **fine-grained** token scoped to the specific org/repo with `Contents: Read/Write` and `Pull requests: Read/Write`, or
   - A **classic** token with the `repo` scope (which already includes PR permissions).
2. Copy the token value into your `.env` as `GITHUB_TOKEN=ghp_...`.
3. Keep the token local. Remote Coder only uses it when a workflow explicitly needs GitHub API access (e.g., syncing edits to a PR).

## Project & agent configuration

`projects.yaml` maps Slack channels to local git repositories. Each entry only needs a relative path (relative to `base_dir`), a default agent, and optional GitHub metadata:

```yaml
base_dir: /home/you/code

projects:
  remote-coder:
    path: remote-coder
    default_agent: codex
    github:
      owner: your-github-handle
      repo: remote-coder
      default_base_branch: main
```

`agents.yaml` lists the CLI commands Remote Coder can launch:

```yaml
agents:
  claude:
    type: claude
    command: ["claude", "--print", "--permission-mode", "acceptEdits", ...]
    working_dir_mode: project
    models:
      default: sonnet
      available: [opus, sonnet, haiku]
```

Commands run once per Slack message, so make sure the CLI you specify supports non-interactive usage. When you want to add a new project or tweak an agent, edit the YAML directly and restart `remote-coder`.

**Make sure you invite the bot to the channel with your project so that it can start listening for messages in that channel**

## Slack commands & PR workflow

- `!use <agent-id>` – switch to a different coding agent for this session.
- `!status` – show the current agent, active model, and history count.
- `!review` – list unresolved GitHub review comments for the session's PR and immediately run the active agent to address them.
- `!reload-projects` – reload `.env`, `projects.yaml`, and `agents.yaml` after running `./scripts/copy_configs.sh`.
- `!setup` – health-check your CLI authentications (inside the container or on bare metal).
- `!end` – end the current session (start a new Slack thread to reset state).
- `!purge` – cancel all running agent tasks and clear all sessions (useful for resetting daemon state without restarting).
- `!help` – show the available commands.

When an agent edits files in a session, Remote Coder creates (or reuses) a branch named `remote-coder-<session-id>`, commits the changes, pushes to `origin`, and opens/updates a pull request against the project’s default base branch. A link to the PR is posted in the Slack thread after every successful push so you can review progress immediately. Make sure each project points to a git repository with a clean working tree and a reachable `origin`, and that `projects.yaml` includes the repository’s GitHub metadata.

## Useful Links

- Slack Socket Mode Docs: <https://api.slack.com/apis/connections/socket>
- Slack App Management: <https://api.slack.com/apps>
- PyGithub: <https://pygithub.readthedocs.io/>

## Personal Notes

1. Using Gemini CLI is kinda slow for some reason. Recommending you use the actual paid stuff first until you hit the limits first like claude code and codex cli before using gemini. Just my opinion. Do what you want.
