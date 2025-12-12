"""Claude Code adapter implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

from ..core.model_mapping import get_cli_model_name
from ..core.models import Agent, AgentType, WorkingDirMode
from .base import AgentAdapter, AgentResult, FileEdit, parse_structured_output

LOGGER = logging.getLogger(__name__)


class ClaudeAdapter(AgentAdapter):
    """Executes single Claude Code runs via the CLI."""

    def __init__(self, agent: Agent) -> None:
        if agent.type != AgentType.CLAUDE:
            raise ValueError(f"ClaudeAdapter requires a CLAUDE agent, got {agent.type}")
        self._agent = agent

    async def run(
        self,
        *,
        task_text: str,
        project_path: str,
        session_id: str,
        conversation_history: Sequence[Dict[str, Any]],
        model: str | None = None,
    ) -> AgentResult:
        command = self._build_command(session_id, model)
        workdir = self._resolve_workdir(project_path)
        env = {**os.environ, **self._agent.env}

        LOGGER.info("Running Claude one-shot command in %s", workdir)
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workdir),
            env=env,
        )

        assert process.stdin is not None
        process.stdin.write(task_text.encode("utf-8") + b"\n")
        await process.stdin.drain()
        process.stdin.close()

        raw_events: list[str] = []
        text_chunks: list[str] = []
        file_edits: list[FileEdit] = []
        errors: list[str] = []

        assert process.stderr is not None
        stderr_task = asyncio.create_task(process.stderr.read())

        # Read stdout in chunks to avoid readline() buffer limit issues
        stdout_stream = process.stdout
        if stdout_stream:
            buffer = ""
            chunk_size = 10 * 1024 * 1024  # 10MB chunks

            while True:
                chunk = await stdout_stream.read(chunk_size)
                if not chunk:
                    break

                buffer += chunk.decode("utf-8", errors="replace")

                # Process complete lines from buffer
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    decoded = line.strip()
                    raw_events.append(decoded)

                    if not decoded:
                        continue

                    parsed = self._parse_json(decoded)
                    if not parsed:
                        continue

                    segments = self._extract_text_segments(parsed)
                    if segments:
                        text_chunks.extend(segments)
                    file_edits.extend(self._extract_file_edits(parsed))
                    errors.extend(self._extract_errors(parsed))

            # Process any remaining data in buffer
            if buffer.strip():
                decoded = buffer.strip()
                raw_events.append(decoded)
                parsed = self._parse_json(decoded)
                if parsed:
                    segments = self._extract_text_segments(parsed)
                    if segments:
                        text_chunks.extend(segments)
                    file_edits.extend(self._extract_file_edits(parsed))
                    errors.extend(self._extract_errors(parsed))

        return_code = await process.wait()
        stderr_raw = await stderr_task
        stderr_output = stderr_raw.decode("utf-8", errors="replace").strip()
        if stderr_output:
            errors.append(stderr_output)

        success = return_code == 0

        output_text = "\n".join(chunk for chunk in text_chunks if chunk).strip()
        raw_output = "\n".join(raw_events + ([stderr_output] if stderr_output else []))
        structured_output = parse_structured_output(output_text or raw_output)

        return AgentResult(
            success=success,
            output_text=output_text or ("\n".join(raw_events).strip() if raw_events else ""),
            file_edits=file_edits,
            errors=[err for err in errors if err],
            session_context={},
            raw_output=raw_output,
            structured_output=structured_output,
        )

    def _build_command(self, session_id: str, model: str | None) -> list[str]:
        # Claude's CLI refuses to reuse session IDs between concurrent runs, and
        # our stateless architecture already feeds prior history manually, so we
        # skip passing --session-id entirely.
        command = list(self._agent.command)

        # Inject model flag if specified
        if model:
            cli_model = get_cli_model_name("claude", model)
            command.extend(["--model", cli_model])

        return command

    def _resolve_workdir(self, project_path: str) -> Path:
        if self._agent.working_dir_mode == WorkingDirMode.PROJECT:
            return Path(project_path)
        if self._agent.fixed_path:
            return self._agent.fixed_path
        raise ValueError("Fixed working directory required for CLAUDE adapter")

    def _parse_json(self, line: str) -> Dict[str, Any] | None:
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    def _extract_text_segments(self, payload: Dict[str, Any]) -> list[str]:
        if payload.get("type") != "assistant":
            return []
        message = payload.get("message")
        if not isinstance(message, dict):
            return []
        segments: list[str] = []
        segments.extend(self._extract_from_content(message.get("content")))
        text_value = message.get("text")
        if isinstance(text_value, str) and text_value.strip():
            segments.append(text_value.strip())
        return segments

    def _extract_from_content(self, content: Any) -> list[str]:
        if not isinstance(content, list):
            return []
        segments: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    segments.append(text.strip())
            elif block_type == "tool_result":
                output = block.get("output") or []
                if isinstance(output, list):
                    for entry in output:
                        if isinstance(entry, dict) and entry.get("type") == "text":
                            text = entry.get("text")
                            if isinstance(text, str) and text.strip():
                                segments.append(text.strip())
        return segments

    def _extract_file_edits(self, payload: Dict[str, Any]) -> list[FileEdit]:
        edits: list[FileEdit] = []
        for candidate in self._iter_tool_payloads(payload):
            path = self._extract_path(candidate)
            if not path:
                continue
            edit_type = str(candidate.get("name") or candidate.get("type") or "edit").lower()
            diff = candidate.get("diff") or candidate.get("delta")
            edits.append(FileEdit(path=path, type=edit_type, diff=diff))
        return edits

    def _iter_tool_payloads(self, payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
        keys = ("tool", "tool_use", "toolInvocation", "toolRequest")
        for key in keys:
            value = payload.get(key)
            if isinstance(value, dict):
                yield value
        message = payload.get("message")
        if isinstance(message, dict):
            yield from self._iter_tool_payloads(message)
        delta = payload.get("delta")
        if isinstance(delta, dict):
            yield from self._iter_tool_payloads(delta)

    def _extract_path(self, payload: Dict[str, Any]) -> str | None:
        possible_keys = ("path", "file_path", "filePath")
        for key in possible_keys:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        input_obj = payload.get("input") or payload.get("arguments") or {}
        if isinstance(input_obj, dict):
            for key in possible_keys:
                value = input_obj.get(key)
                if isinstance(value, str) and value:
                    return value
        return None

    def _extract_errors(self, payload: Dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if payload.get("type") == "error":
            detail = payload.get("error")
            if isinstance(detail, dict):
                message = detail.get("message") or detail.get("text")
                if isinstance(message, str):
                    errors.append(message)
        return errors
