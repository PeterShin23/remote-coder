"""Async wrapper around a running agent subprocess."""

from __future__ import annotations

import asyncio
import logging
from asyncio import StreamReader, Task
from asyncio.subprocess import Process
from pathlib import Path
from typing import Awaitable, Callable, Dict, Optional

from ..core.errors import ProcessError

LOGGER = logging.getLogger(__name__)

OutputCallback = Callable[[str, str], Awaitable[None]]


class AgentProcess:
    """Manages a single long-running agent subprocess."""

    def __init__(
        self,
        command: list[str],
        cwd: Path,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        self._command = command
        self._cwd = cwd
        self._env = env
        self._process: Optional[Process] = None
        self._stdout_task: Optional[Task[None]] = None
        self._stderr_task: Optional[Task[None]] = None
        self._on_output: Optional[OutputCallback] = None

    @property
    def is_running(self) -> bool:
        return bool(self._process and self._process.returncode is None)

    @property
    def returncode(self) -> Optional[int]:
        return self._process.returncode if self._process else None

    async def start(self, on_output: OutputCallback) -> None:
        if self.is_running:
            raise ProcessError("Process already running")
        if not self._cwd.exists():
            raise ProcessError(f"Working directory does not exist: {self._cwd}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._cwd),
                env=self._env,
            )
        except OSError as exc:
            raise ProcessError(f"Failed to start process {self._command}: {exc}") from exc

        LOGGER.info("Started agent process pid=%s cmd=%s", self._process.pid, self._command)
        self._on_output = on_output
        self._stdout_task = asyncio.create_task(self._stream_output(self._process.stdout, "stdout"))
        self._stderr_task = asyncio.create_task(self._stream_output(self._process.stderr, "stderr"))

    async def send_input(self, data: str) -> None:
        if not self.is_running or not self._process or not self._process.stdin:
            raise ProcessError("Cannot write to a stopped process")
        self._process.stdin.write(data.encode("utf-8"))
        if not data.endswith("\n"):
            self._process.stdin.write(b"\n")
        await self._process.stdin.drain()

    async def stop(self, grace_seconds: float = 5.0) -> None:
        if not self._process:
            return

        process = self._process
        if process.returncode is None:
            LOGGER.info("Stopping agent process pid=%s", process.pid)
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=grace_seconds)
            except asyncio.TimeoutError:
                LOGGER.warning("Process pid=%s did not exit in time, killing", process.pid)
                process.kill()
                await process.wait()

        await self._cleanup_streams()
        self._process = None

    async def wait(self) -> int:
        if not self._process:
            raise ProcessError("Process not started")
        return await self._process.wait()

    async def _stream_output(self, reader: Optional[StreamReader], stream_name: str) -> None:
        if reader is None:
            return
        while True:
            try:
                line = await reader.readline()
            except asyncio.CancelledError:
                break
            if not line:
                break
            await self._emit(stream_name, line.decode("utf-8", errors="replace"))

    async def _emit(self, stream_name: str, text: str) -> None:
        if not self._on_output:
            return
        try:
            await self._on_output(stream_name, text.rstrip("\n"))
        except Exception:  # pragma: no cover - defensive logging
            LOGGER.exception("Output callback failed for %s", stream_name)

    async def _cleanup_streams(self) -> None:
        tasks = [t for t in (self._stdout_task, self._stderr_task) if t]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._stdout_task = None
        self._stderr_task = None
        self._on_output = None
