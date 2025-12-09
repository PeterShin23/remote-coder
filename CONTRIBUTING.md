# Contributing to Remote Coder

Thanks for helping shape Remote Coder! This document explains how to set up a development environment, run tests, and propose changes.

## Development setup

1. Fork the repository on GitHub, then clone **your fork** locally:
   ```bash
   git clone git@github.com:<your-user>/remote-coder.git
   cd remote-coder
   ```
2. Install Python 3.11+ and [uv](https://github.com/astral-sh/uv).
3. Create a virtual environment and install dependencies:
   ```bash
   uv venv
   source .venv/bin/activate
   uv pip install -e ".[dev]"
   ```
4. Copy the configuration templates into a dedicated dev config directory:
   ```bash
   mkdir -p dev-config
   cp .env.example dev-config/.env
   cp config/projects.yaml.example dev-config/projects.yaml
   cp config/agents.yaml dev-config/agents.yaml
   ```
5. Fill in `dev-config/.env` with valid Slack and GitHub tokens (see the README for details).

## Running the daemon in development

Remote Coder expects to read configuration from a directory that contains `.env`, `projects.yaml`, and `agents.yaml`. With the files in `dev-config/`, launch the daemon via:

```bash
uv run remote-coder --config-dir "$(pwd)/dev-config"
```

You can also run it directly with `python -m src.main --config-dir "$(pwd)/dev-config"` if you prefer.

## Tests and linting

- **Unit tests:** `uv run pytest`
- **Linting/format:** `uv run ruff check .`

Please run both before opening a pull request. If you add new behavior, include targeted unit tests when possible.

## Coding style

- Prefer type hints and dataclasses where appropriate.
- Keep modules ASCII-only unless there is a compelling reason to use Unicode.
- Use concise, purposeful comments only when the intent of the code is non-obvious.
- Follow the existing logging and error-handling patterns (use `ConfigError`, `RemoteCoderError`, etc.).

## Pull request guidelines

1. Always work from your own fork; direct clones of the upstream repository will not be considered for contribution.
2. Open an issue or discussion if you’re planning a large change.
2. Keep pull requests focused—small, reviewable chunks are easier to merge.
3. Include screenshots or terminal output when changing user-visible behavior.
4. Update documentation (README, docs/, or inline comments) when you add or change features.
6. Ensure the CI pipeline passes (tests + lint).

Thanks again for contributing! If you have questions, open a GitHub Discussion or reach out via issues.
