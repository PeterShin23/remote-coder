"""Manage lifecycle of agent subprocesses per session."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict
from uuid import UUID

from .agent_process import AgentProcess, OutputCallback
from ..core.errors import ProcessError
from ..core.models import Agent, Project, WorkingDirMode

LOGGER = logging.getLogger(__name__)


@dataclass
class _ProcessHandle:
    process: AgentProcess
    agent_id: str
    project_id: str


class ProcessManager:
    """Creates and tracks agent processes per Slack session thread."""

    def __init__(self) -> None:
        self._processes: Dict[UUID, _ProcessHandle] = {}
        self._lock = asyncio.Lock()

    async def ensure_process(
        self,
        session_id: UUID,
        project: Project,
        agent: Agent,
        on_output: OutputCallback,
    ) -> AgentProcess:
        """Start or reuse the agent process for a session."""
        async with self._lock:
            handle = self._processes.get(session_id)
            if handle and handle.agent_id == agent.id and handle.process.is_running:
                return handle.process

            if handle:
                await handle.process.stop()

            process = await self._launch_process(project, agent, on_output)
            self._processes[session_id] = _ProcessHandle(
                process=process,
                agent_id=agent.id,
                project_id=project.id,
            )
            return process

    async def send_to_process(self, session_id: UUID, text: str) -> None:
        async with self._lock:
            handle = self._processes.get(session_id)
            if not handle or not handle.process.is_running:
                raise ProcessError(f"No running process for session {session_id}")
            await handle.process.send_input(text)

    async def stop_process(self, session_id: UUID) -> None:
        async with self._lock:
            handle = self._processes.pop(session_id, None)
        if handle:
            await handle.process.stop()

    async def stop_processes_by_agent(self, agent_id: str) -> list[UUID]:
        async with self._lock:
            matching = [sid for sid, handle in self._processes.items() if handle.agent_id == agent_id]
            handles = [(sid, self._processes.pop(sid)) for sid in matching]
        await asyncio.gather(*(handle.process.stop() for _, handle in handles), return_exceptions=True)
        return matching

    async def stop_all_processes(self) -> list[UUID]:
        async with self._lock:
            handles = list(self._processes.items())
            self._processes.clear()
        await asyncio.gather(*(handle.process.stop() for _, handle in handles), return_exceptions=True)
        return [sid for sid, _ in handles]

    async def shutdown(self) -> None:
        async with self._lock:
            handles = list(self._processes.values())
            self._processes.clear()
        await asyncio.gather(*(handle.process.stop() for handle in handles), return_exceptions=True)

    async def _launch_process(
        self,
        project: Project,
        agent: Agent,
        on_output: OutputCallback,
    ) -> AgentProcess:
        cwd = self._determine_working_dir(project, agent)
        env = os.environ.copy()
        process = AgentProcess(command=list(agent.command), cwd=cwd, env=env)
        await process.start(on_output)
        return process

    def _determine_working_dir(self, project: Project, agent: Agent) -> Path:
        if agent.working_dir_mode == WorkingDirMode.PROJECT:
            return project.path
        if agent.working_dir_mode == WorkingDirMode.FIXED and agent.fixed_path:
            return agent.fixed_path
        raise ProcessError(f"No working directory available for agent {agent.id}")
