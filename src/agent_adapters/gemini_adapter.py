"""Gemini CLI adapter implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Sequence

from ..core.model_mapping import get_cli_model_name
from ..core.models import Agent, AgentType, WorkingDirMode
from .base import AgentAdapter, AgentResult, FileEdit, parse_structured_output

LOGGER = logging.getLogger(__name__)


class GeminiAdapter(AgentAdapter):
    """Executes Gemini CLI commands in one-shot mode."""

    def __init__(self, agent: Agent) -> None:
        if agent.type != AgentType.GEMINI:
            raise ValueError(f"GeminiAdapter requires a GEMINI agent, got {agent.type}")
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
        # Gemini CLI takes the prompt as a positional argument for one-shot mode
        command = list(self._agent.command)

        # Inject model flag if specified (before the prompt)
        # Skip -m flag for "auto" to let CLI auto-select
        if model and model != "auto":
            cli_model = get_cli_model_name("gemini", model)
            command.extend(["-m", cli_model])

        command.append(task_text)

        workdir = self._resolve_workdir(project_path)
        env = {**os.environ, **self._agent.env}

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workdir),
            env=env,
        )

        raw_events: list[str] = []
        text_chunks: list[str] = []
        file_edits: list[FileEdit] = []
        errors: list[str] = []
        streaming_buffer = ""  # Buffer for delta messages

        assert process.stderr is not None
        stderr_task = asyncio.create_task(process.stderr.read())

        # Read stdout in chunks to avoid readline() buffer limit issues
        stdout_stream = process.stdout
        if stdout_stream:
            buffer = ""
            chunk_size = 1024 * 1024  # 1MB chunks

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

                    # Try to parse as JSON
                    parsed = self._parse_json(decoded)
                    if parsed:
                        # Handle streaming delta messages
                        if parsed.get("type") == "message" and parsed.get("role") == "assistant":
                            content = parsed.get("content", "")
                            is_delta = parsed.get("delta", False)

                            if is_delta:
                                # Accumulate delta chunks
                                streaming_buffer += content
                            else:
                                # Complete message (not a delta)
                                if streaming_buffer:
                                    # Flush any buffered delta content first
                                    text_chunks.append(streaming_buffer)
                                    streaming_buffer = ""
                                if content:
                                    text_chunks.append(content)

                        file_edits.extend(self._extract_file_edits(parsed))
                        errors.extend(self._extract_errors(parsed))
                    else:
                        # If not JSON, treat as plain text output
                        text_chunks.append(decoded)

            # Process any remaining data in buffer
            if buffer.strip():
                decoded = buffer.strip()
                raw_events.append(decoded)
                parsed = self._parse_json(decoded)
                if parsed:
                    # Handle streaming delta messages
                    if parsed.get("type") == "message" and parsed.get("role") == "assistant":
                        content = parsed.get("content", "")
                        is_delta = parsed.get("delta", False)

                        if is_delta:
                            streaming_buffer += content
                        else:
                            if streaming_buffer:
                                text_chunks.append(streaming_buffer)
                                streaming_buffer = ""
                            if content:
                                text_chunks.append(content)

                    file_edits.extend(self._extract_file_edits(parsed))
                    errors.extend(self._extract_errors(parsed))
                else:
                    text_chunks.append(decoded)

        # Flush any remaining buffered content
        if streaming_buffer:
            text_chunks.append(streaming_buffer)

        return_code = await process.wait()
        stderr_raw = await stderr_task
        stderr_output = stderr_raw.decode("utf-8", errors="replace").strip()

        # Filter out informational messages that aren't actual errors
        if stderr_output and not self._is_informational_stderr(stderr_output):
            errors.append(stderr_output)

        success = return_code == 0

        # Combine all text chunks (already properly assembled from deltas)
        # Each chunk is a complete message, so join with newlines
        output_text = "\n".join(chunk for chunk in text_chunks if chunk).strip()
        if not output_text and raw_events:
            output_text = "\n".join(raw_events).strip()
        raw_output = "\n".join(raw_events + ([stderr_output] if stderr_output else []))
        structured_output = parse_structured_output(output_text or raw_output)

        return AgentResult(
            success=success,
            output_text=output_text,
            file_edits=file_edits,
            errors=[err for err in errors if err],
            session_context={},
            raw_output=raw_output,
            structured_output=structured_output,
        )

    def _resolve_workdir(self, project_path: str) -> Path:
        if self._agent.working_dir_mode == WorkingDirMode.PROJECT:
            return Path(project_path)
        if self._agent.fixed_path:
            return self._agent.fixed_path
        raise ValueError("Fixed working directory required for Gemini adapter")

    def _parse_json(self, line: str) -> Dict[str, Any] | None:
        """Try to parse a line as JSON."""
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    def _extract_file_edits(self, payload: Dict[str, Any]) -> list[FileEdit]:
        """Extract file edits from JSON payload."""
        edits: list[FileEdit] = []

        # Look for tool use events that might indicate file operations
        for tool_payload in self._iter_tool_payloads(payload):
            path = self._extract_path(tool_payload)
            if not path:
                continue
            edit_type = str(tool_payload.get("name") or tool_payload.get("type") or "edit").lower()
            diff = tool_payload.get("diff") or tool_payload.get("delta")
            edits.append(FileEdit(path=path, type=edit_type, diff=diff))

        return edits

    def _iter_tool_payloads(self, payload: Dict[str, Any]):
        """Iterate over tool-related payloads."""
        keys = ("tool", "tool_use", "toolInvocation", "toolRequest")
        for key in keys:
            value = payload.get(key)
            if isinstance(value, dict):
                yield value
        message = payload.get("message")
        if isinstance(message, dict):
            yield from self._iter_tool_payloads(message)

    def _extract_path(self, payload: Dict[str, Any]) -> str | None:
        """Extract file path from tool payload."""
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
        """Extract errors from JSON payload."""
        errors: list[str] = []
        if payload.get("type") == "error":
            detail = payload.get("error")
            if isinstance(detail, dict):
                message = detail.get("message") or detail.get("text")
                if isinstance(message, str):
                    errors.append(message)
        return errors

    def _is_informational_stderr(self, stderr_text: str) -> bool:
        """Check if stderr output is just informational, not an actual error."""
        lowered = stderr_text.lower()

        # Common informational messages from Gemini CLI
        informational_phrases = [
            "loaded cached credentials",
            "loading credentials",
            "using model",
            "session started",
            "connecting to",
        ]

        return any(phrase in lowered for phrase in informational_phrases)

