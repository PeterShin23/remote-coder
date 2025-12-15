"""Shared data passed to command handlers."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Project, Session


@dataclass(frozen=True)
class CommandContext:
    session: Session
    project: Project
    channel: str
    thread_ts: str
