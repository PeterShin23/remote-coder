# Dev Notes and Tradeoffs

This file is for me, so I remember why I made certain choices and don’t over-engineer this thing later.

---

## Architecture snapshot

remote-coder today:

- Python daemon running on my machine.
- Slack (Socket Mode) as the UI.
- Each Slack thread = one session, keyed by `(channel_id, thread_ts)`.
- For each message in a session:
  - Resolve project via `projects.yaml`.
  - Pick active agent (`claude`, `codex`, later `gemini`).
  - Spawn a one-shot CLI subprocess (no persistent PTY).
  - CLI edits code / runs commands in the repo.
  - I detect git changes, commit, push, create/update PR.
  - Post status + PR link back into the Slack thread.

Persistent history lives in:

- Slack thread (conversation + links).
- Git commits.
- GitHub PRs.

No HTTP LLM APIs in the main flow, only local CLIs.

---

## CLI vs HTTP SDK

I’m intentionally driving the CLIs (Claude Code, Codex CLI, Gemini CLI, etc.) instead of using the Anthropic/OpenAI/Gemini HTTP APIs.

### Why CLI-first

- Reuses my existing subscriptions. If I can run the CLI, I can use remote-coder.
- The CLI already acts like a coding agent: reads/writes files, runs tests, applies diffs.
- I don’t have to store or manage API keys in this project.
- Local-first: everything happens on my machine.

### What I give up

- Less structured telemetry (no clean tool traces, token usage, etc.).
- Tighter coupling to CLI flags and output formats.
- Harder to scale this to multi-user / hosted mode.

### Why I’m not switching to SDK right now

- API billing is separate from subscriptions. I’d end up needing API keys and pay-per-token.
- I’d have to build the entire coding agent logic myself instead of offloading it to the CLIs.
- More complexity for not much gain in the personal-dev-tool use case.

If I ever add an SDK path, it will be a separate `ApiAgentAdapter`, not a replacement.

---

## Persistence: no DB (for now)

I thought about adding SQLite for sessions and PR mappings. For how I actually use this, it doesn’t add much value.

Right now:

- Slack threads already keep the conversation and PR links.
- Git + GitHub already store the actual changes and review history.
- I usually work a thread until the PR is done, then move on. I don’t really “resume” old sessions.

So:

- Sessions stay in memory only, keyed by `(channel_id, thread_ts)`.
- If the daemon restarts, any new message just starts fresh.
- If I really need to reconstruct something, I can read the Slack thread and the PR.

If I ever need analytics or multi-user / multi-platform support, I can add a `SessionStore` abstraction and plug SQLite in later.

---

## One-shot CLI runs vs persistent PTY

I chose one-shot executions instead of keeping a long-lived PTY per thread.

One-shot approach:

- Each Slack message → start a CLI process → wait → done.
- No need to manage “is this PTY still alive?”.
- Works nicely with the idea of sessions being short-lived.

Persistent PTY would:

- Allow more “chatty” back-and-forth with the CLI itself.
- Avoid process startup costs on every message.

But it adds complexity I don’t need right now: reconnect logic, health checks, more edge cases.

---

## `!purge` vs just `!end`

Current session commands:

- `!use <agent>` – set agent: `claude`, `codex`, (later `gemini`).
- `!status` – show session info.
- `!review` – list unresolved GitHub review comments for this session’s PR.
- `!end` – end this session (start a new Slack thread to truly reset).
- `!help` – show commands.

I’m adding:

- `!purge` – global finish button.

Reason:

- `!end` only affects one thread and doesn’t guarantee that a long-running subprocess stops.
- Sometimes I just want to kill everything and reset the daemon without restarting the process.

`!purge` will:

- Cancel all active agent tasks.
- Kill all underlying subprocesses.
- Clear all in-memory sessions.
- Confirm in Slack that the system is now clean.

This matches how I think about the tool: sessions are expendable, and I’d rather have a hard reset than chase down stray processes.

---

## Model selection (intentionally deferred)

I went back and forth on model selection per agent (e.g. Claude Sonnet vs Haiku vs Opus).

Ideas I considered:

- Per-model YAML config.
- Trying to list models via CLI commands.
- Free-form `!use-model <id>` that passes `--model <id>` through.

Conclusion for now:

- This is not critical to how I use the tool today.
- Model listing via CLIs is messy and vendor-specific.
- YAML-per-model will get gross quickly.

So I’m deferring model selection. The architecture can support an `active_model` string later, but I’m not wiring it up until I actually feel the pain.

---

## Multi-agent via adapters (Claude, Codex, Gemini)

Agents are handled via an adapter pattern:

- Given:
  - task text,
  - project path,
  - session metadata,
- The adapter:
  - builds the CLI command,
  - runs it in the project directory,
  - passes in the task (stdin or args),
  - reads stdout/stderr,
  - returns a result object with:
    - text for Slack,
    - success/failure info,
    - optionally more structured details.

This makes it straightforward to:

- Add another CLI coding agent.
- Keep Git, GitHub, and Slack logic shared.
- Swap or extend agents without touching the whole system.

---

## Overall philosophy

- Optimize for “single power user with strong tools installed locally.”
- Let CLIs do the heavy lifting; remote-coder is the glue.
- Avoid extra infrastructure (no DB, no HTTP APIs) until there is a clear, real need.
- Provide simple control primitives:
  - per-thread session control (`!end`, `!use`, `!status`),
  - global kill (`!purge`).

Future work (SDK-based agents, SQLite, fancier model selection) should be judged against this baseline so the project doesn’t drift into over-engineering.
