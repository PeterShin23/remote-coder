"""Codex adapter implementation."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any, Dict, Sequence

from ..core.models import Agent, AgentType, WorkingDirMode
from .base import AgentAdapter, AgentResult, FileEdit, parse_structured_output


class CodexAdapter(AgentAdapter):
    """Executes Codex CLI commands in one-shot mode."""

    _FILE_EDIT_PATTERNS = [
        re.compile(r"^(EDIT|CREATE|DELETE)\s+(.+)$", re.IGNORECASE),
        re.compile(r"^Applying (?:edit|patch) to\s+(.+)$", re.IGNORECASE),
        re.compile(r"^Wrote\s+(.+)$", re.IGNORECASE),
    ]

    def __init__(self, agent: Agent) -> None:
        if agent.type != AgentType.CODEX:
            raise ValueError(f"CodexAdapter requires a CODEX agent, got {agent.type}")
        self._agent = agent

    async def run(
        self,
        *,
        task_text: str,
        project_path: str,
        session_id: str,
        conversation_history: Sequence[Dict[str, Any]],
    ) -> AgentResult:
        command = list(self._agent.command)
        workdir = self._resolve_workdir(project_path)
        env = {**os.environ, **self._agent.env}

        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workdir),
            env=env,
        )

        # Increase buffer limit for large responses (default is 64KB)
        if process.stdout:
            process.stdout._limit = 10 * 1024 * 1024  # 10MB
        if process.stderr:
            process.stderr._limit = 10 * 1024 * 1024  # 10MB

        assert process.stdin is not None
        stdin_payload = (task_text + "\n").encode("utf-8")
        process.stdin.write(stdin_payload)
        await process.stdin.drain()
        process.stdin.close()

        stdout_stream = process.stdout
        stderr_stream = process.stderr
        stdout_bytes, stderr_bytes = await asyncio.gather(
            stdout_stream.read() if stdout_stream else asyncio.sleep(0, result=b""),
            stderr_stream.read() if stderr_stream else asyncio.sleep(0, result=b""),
        )
        return_code = await process.wait()

        stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
        success = return_code == 0

        file_edits = self._parse_file_edits(stdout_text)
        errors = []
        if not success:
            if stderr_text:
                errors.append(stderr_text)
            else:
                errors.append("Codex command failed")

        output_text = self._extract_primary_output(stdout_text)
        if not output_text:
            output_text = stdout_text or stderr_text
        raw_output = "\n".join(filter(None, [stdout_text, stderr_text]))
        structured_output = parse_structured_output(output_text or raw_output)

        return AgentResult(
            success=success,
            output_text=output_text,
            file_edits=file_edits,
            errors=errors,
            session_context={},
            raw_output=raw_output,
            structured_output=structured_output,
        )

    def _resolve_workdir(self, project_path: str) -> Path:
        if self._agent.working_dir_mode == WorkingDirMode.PROJECT:
            return Path(project_path)
        if self._agent.fixed_path:
            return self._agent.fixed_path
        raise ValueError("Fixed working directory required for Codex adapter")

    def _parse_file_edits(self, stdout_text: str) -> list[FileEdit]:
        edits: list[FileEdit] = []
        for line in stdout_text.splitlines():
            line = line.strip()
            if not line:
                continue
            for pattern in self._FILE_EDIT_PATTERNS:
                match = pattern.match(line)
                if not match:
                    continue
                if pattern.groups == 2:
                    edit_type = match.group(1).lower()
                    path = match.group(2).strip()
                else:
                    edit_type = "edit"
                    path = match.group(match.lastindex or 1).strip()
                edits.append(FileEdit(path=path, type=edit_type))
                break
        return edits

    def _extract_primary_output(self, stdout_text: str) -> str:
        lines = [line.rstrip() for line in stdout_text.splitlines()]
        capture = False
        collected: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not capture:
                if stripped.lower() == "codex":
                    capture = True
                continue
            if self._should_stop_capture(stripped):
                break
            collected.append(line)

        cleaned = "\n".join(collected).strip()
        if cleaned:
            return cleaned
        return self._fallback_output(lines)

    def _should_stop_capture(self, stripped: str) -> bool:
        if not stripped:
            return False
        return self._is_metadata_line(stripped)

    def _fallback_output(self, lines: list[str]) -> str:
        buffer: list[str] = []
        capturing = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if capturing and buffer:
                    buffer.append("")
                continue
            if self._is_metadata_line(stripped):
                if capturing and buffer:
                    break
                continue
            capturing = True
            buffer.append(line)
        return "\n".join(buffer).strip()

    def _is_metadata_line(self, stripped: str) -> bool:
        lowered = stripped.lower()
        if lowered in {"user", "assistant", "system", "thinking", "result", "codex"}:
            return True
        prefixes = (
            "tokens used",
            "workdir:",
            "model:",
            "provider:",
            "approval:",
            "sandbox:",
            "reasoning",
            "session id:",
            "reading prompt",
            "openai codex",
            "--------",
            "recent context:",
            "current request:",
            "task",
            "skill",
            "bash",
            "todo",
            "plan",
            "cost",
        )
        if any(lowered.startswith(prefix) for prefix in prefixes):
            return True
        if lowered.startswith("**") and lowered.endswith("**"):
            return True
        return False
