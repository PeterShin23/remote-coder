# Security Policy

## Supported versions

Remote Coder is currently in public alpha (`v0.0.1-alpha.x`). Security fixes are applied to the latest alpha release only.

## Reporting a vulnerability

Please **do not** open public GitHub issues for security problems.

- Use GitHub’s “[Report a vulnerability](https://github.com/PeterShin23/remote-coder/security/advisories/new)” workflow, or
- Email **psshin.code@gmail.com** with details. Include reproduction steps, logs, and any proof-of-concept material you can share privately.

We aim to acknowledge new reports within five business days.

## Handling secrets

- Never commit Slack, GitHub, or CLI tokens to the repository.
- Store credentials only in your config directory’s `.env` file or in local environment variables.
- Treat generated branches and pull requests as potentially sensitive; scrub logs before sharing them.

If you suspect that a token has leaked, revoke it immediately through Slack/GitHub and generate a new one.
