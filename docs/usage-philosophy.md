# Remote Coder Usage Philosophy

## Subscription CLI-Based Approach

Remote Coder uses **subscription-based coding tools** via their command-line interfaces (CLIs). This is a deliberate architectural choice that differs from many AI coding assistants.

## Supported Agents

Remote Coder integrates with the following coding agents:

1. **Claude Code** - Requires Claude Pro or Claude Max subscription
2. **Codex** - Requires ChatGPT or Codex subscription
3. **Gemini Code Assist** - Requires Google Cloud subscription
4. **Qwen Code** (via OpenRouter) - Uses OpenRouter API key as an exception

## Why Subscription CLIs?

### 1. No Metered API Costs

Subscription-based CLIs provide unlimited usage within the subscription terms. You don't pay per token or per request, making it economical for intensive coding sessions.

### 2. Built-in Authentication

Each CLI handles its own authentication flow. Once logged in, the CLI manages token refresh and session persistence without additional configuration.

### 3. Feature Parity

Subscription CLIs often have access to the latest model versions and features before they're available via metered APIs.

### 4. Simpler Configuration

You don't need to manage API keys, rate limits, or billing alerts. The CLI subscription is a separate concern from your Remote Coder setup.

## What We DON'T Use

Remote Coder explicitly **does not use** metered API keys like:

- `CLAUDE_API_KEY`
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`

These environment variables are not referenced in the codebase (except for documentation purposes).

## Exception: OpenRouter for Qwen

The Qwen Code agent is an exception to the subscription rule. It uses OpenRouter's API with the `OPENROUTER_API_KEY` environment variable. This provides access to Qwen models without requiring a separate subscription.

If you prefer to avoid metered APIs entirely, simply don't configure the Qwen agent in `config/agents.yaml`.

## Setting Up Agents

Each agent requires its CLI to be installed and authenticated:

1. **Claude Code**: Install via npm/pip, run `claude` and complete `/login` flow
2. **Codex**: Install via instructions, run `codex` and authenticate
3. **Gemini**: Install via Google Cloud SDK, run `gemini` and authenticate
4. **Qwen**: Install via npm/pip, set `OPENROUTER_API_KEY` environment variable

See the main README for detailed setup instructions, and `docs/cloud-vm-setup.md` for remote deployment guidance.

## Cost Comparison

### Subscription Model (Recommended)

- Fixed monthly cost (e.g., $20-50/month per subscription)
- Unlimited usage within fair use policy
- Predictable billing

### Metered API Model (Not Used)

- Pay per token/request
- Costs can be unpredictable during intensive use
- Requires careful rate limiting and cost monitoring

For a coding assistant that runs continuously and handles multiple projects, the subscription model provides better value and peace of mind.

## Summary

Remote Coder's philosophy prioritizes:

- **Predictable costs** through subscriptions
- **Simplified setup** via CLI authentication
- **Feature access** to the latest model capabilities

This approach makes Remote Coder ideal for:

- Development teams with existing AI coding subscriptions
- Solo developers who want unlimited coding assistance
- Cloud VM deployments where multiple projects are managed continuously
