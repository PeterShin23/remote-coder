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
   uv pip install -e
   ```
4. Copy the configuration templates:
   ```bash
   cp .env.example .env
   cp config/projects.yaml.example config/projects.yaml
   ```
5. Fill in `.env` with valid Slack and GitHub tokens (see the README for details).

Remote Coder expects to read configuration from a directory that contains `.env`, `projects.yaml`, and `agents.yaml`. By default it uses `~/.remote-coder`. After preparing files in `config/` and `.env` in the root directory, copy them into `~/.remote-coder` (look at `scripts/copy_configs.sh`)

## Running the daemon in development

```bash
uv run remote-coder  # Over remote-coder if you're in venv
```

You can also run it directly with `python -m src.main` if you prefer.

## Testing on another device (uv tool)

You can install and test Remote Coder directly from Git on any machine using `uv tool`. This lets you verify changes without publishing a release.

- Install from a branch:
  ```bash
  uv tool install "git+https://github.com/<you>/remote-coder.git@my-branch"
  ```
- Install from a specific commit (reproducible):
  ```bash
  uv tool install "git+https://github.com/<you>/remote-coder.git@abcdef1234"
  ```
- Install from a tag:
  ```bash
  uv tool install "git+https://github.com/<you>/remote-coder.git@v1.2.3"
  ```
- If the project lives in a subdirectory (not the case here, but useful for forks/experiments):
  ```bash
  uv tool install "git+https://github.com/<you>/repo.git@my-branch#subdirectory=path/to/subdir"
  ```
- Force a refresh if already installed:
  ```bash
  uv tool install --reinstall "git+https://github.com/<you>/remote-coder.git@my-branch"
  ```
- Uninstall the tool:
  ```bash
  uv tool uninstall remote-coder
  ```

Local dev without pushing changes:

```bash
uv tool install --path . --editable
# later, to refresh after changes
uv tool install --path . --editable --reinstall
```

Recommended workflow: keep `main` stable; test from a feature branch using `@branch`, and pin to a commit (`@<sha>`) when you need deterministic testing on other machines.

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
3. Keep pull requests focused—small, reviewable chunks are easier to merge.
4. Include screenshots or terminal output when changing user-visible behavior.
5. Update documentation (README, docs/, or inline comments) when you add or change features.
6. Ensure the CI pipeline passes (tests + lint).

Thanks again for contributing! If you have questions, open a GitHub Discussion or reach out via issues.
