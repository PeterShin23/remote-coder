"""Model name mappings for CLI agents.

This module contains the mappings between user-facing model names and the actual
CLI model identifiers. All model name translations happen here for easy maintenance.
"""

from typing import Dict

# Claude: User-facing names match CLI names directly
CLAUDE_MODELS: Dict[str, str] = {
    "opus": "opus",
    "sonnet": "sonnet",
    "haiku": "haiku",
}

# Codex: User-facing simplified names → CLI model identifiers
CODEX_MODELS: Dict[str, str] = {
    "base": "gpt-5.1-codex",
    "max": "gpt-5.1-codex-max",
}

# Gemini: User-facing names map to CLI model identifiers
# Note: "auto" is handled specially in GeminiAdapter - no -m flag is passed for auto-select
GEMINI_MODELS: Dict[str, str] = {
    "pro": "gemini-2.5-pro",
    "flash": "gemini-2.5-flash",
}


def get_cli_model_name(agent_type: str, user_model_name: str) -> str:
    """
    Translate a user-facing model name to the CLI model identifier.

    Args:
        agent_type: The agent type (e.g., "claude", "codex", "gemini")
        user_model_name: The user-facing model name (e.g., "base", "max")

    Returns:
        The CLI model identifier to pass to the agent CLI

    Raises:
        ValueError: If the model name is not recognized for this agent
    """
    agent_type_lower = agent_type.lower()

    if agent_type_lower == "claude":
        mapping = CLAUDE_MODELS
    elif agent_type_lower == "codex":
        mapping = CODEX_MODELS
    elif agent_type_lower == "gemini":
        mapping = GEMINI_MODELS
    else:
        raise ValueError(f"Unknown agent type: {agent_type}")

    if user_model_name not in mapping:
        raise ValueError(
            f"Unknown model '{user_model_name}' for agent '{agent_type}'. "
            f"Available: {list(mapping.keys())}"
        )

    return mapping[user_model_name]
