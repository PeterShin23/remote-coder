# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.1-alpha.1] - 2025-02-15

### Added

- `remote-coder` CLI entrypoint with `--config-dir` flag (defaulting to `~/.remote-coder`).
- Config loader that reads `.env`, `projects.yaml`, and `agents.yaml`, plus `REMOTE_CODER_AGENTS` filtering.
- Public alpha quickstart docs, Slack/GitHub setup guidance, and agent selection notes.
- Community docs: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`.
- `!reload-projects` Slack command to pick up `.env` and `.yaml` changes without restarting.

### Changed

- `pyproject.toml` version bumped to `0.0.1-alpha.1` and script points to `src.main:cli`.
- `.env.example` updated to reflect config-dir workflow and `SLACK_ALLOWED_USER_IDS`.
