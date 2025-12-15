"""Central registry of supported Slack commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Sequence, Tuple


@dataclass(frozen=True)
class CommandSpec:
    """Metadata describing a single supported Slack command."""

    name: str
    handler_id: str
    usage: str
    description: str
    aliases: Tuple[str, ...] = ()

    @property
    def all_names(self) -> Tuple[str, ...]:
        return (self.name, *self.aliases)

    def alias_display(self) -> str:
        """Return formatted alias hint for help output."""
        if not self.aliases:
            return ""
        rendered = ", ".join(f"!{alias}" for alias in self.aliases)
        return f" (aliases: {rendered})"


def _build_specs() -> Tuple[CommandSpec, ...]:
    return (
        CommandSpec(
            name="use",
            handler_id="session.use",
            usage="!use <agent> [model]",
            description="Switch to a different agent and optionally specify model.",
        ),
        CommandSpec(
            name="status",
            handler_id="session.status",
            usage="!status",
            description="Show session metadata and stored message count.",
        ),
        CommandSpec(
            name="end",
            handler_id="session.end",
            usage="!end",
            description="End the current session (start a new Slack thread to reset).",
        ),
        CommandSpec(
            name="review",
            handler_id="review.pending",
            usage="!review",
            description="List unresolved GitHub review comments for the session's PR.",
        ),
        CommandSpec(
            name="purge",
            handler_id="maintenance.purge",
            usage="!purge",
            description="Cancel all running agent tasks and clear sessions.",
        ),
        CommandSpec(
            name="agents",
            handler_id="catalog.agents",
            usage="!agents",
            description="List all configured agents.",
        ),
        CommandSpec(
            name="models",
            handler_id="catalog.models",
            usage="!models",
            description="List available models per agent.",
        ),
        CommandSpec(
            name="reload-projects",
            handler_id="maintenance.reload_projects",
            usage="!reload-projects",
            description="Reload configuration files without restarting the daemon.",
        ),
        CommandSpec(
            name="stash",
            handler_id="maintenance.stash",
            usage="!stash",
            description="Stash local changes to allow the session to start.",
        ),
        CommandSpec(
            name="help",
            handler_id="catalog.help",
            usage="!help",
            description="Show this command list.",
            aliases=("commands",),
        ),
    )


COMMAND_SPECS: Tuple[CommandSpec, ...] = _build_specs()
COMMAND_LOOKUP: Dict[str, CommandSpec] = {
    key: spec for spec in COMMAND_SPECS for key in spec.all_names
}


def get_command_spec(name: str) -> Optional[CommandSpec]:
    """Return the command spec for a given name or alias."""
    return COMMAND_LOOKUP.get(name.lower())


def iter_command_specs() -> Sequence[CommandSpec]:
    """Return the immutable list of command specs in display order."""
    return COMMAND_SPECS
