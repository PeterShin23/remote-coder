"""Executes agent tasks based on router inputs."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Optional, Sequence

from ..agent_adapters import AgentAdapter, AgentResult
from .config import Config
from .git_workflow import GitWorkflowService
from .conversation import InteractionClassifier, SessionManager
from .models import Agent, ConversationMessage, Project, Session

LOGGER = logging.getLogger(__name__)

CODE_TASK_WRAPPER = """You are Remote Coder, an autonomous developer working inside the user's repository.

1. Carefully read the latest Slack request and decide whether it requires code changes.
2. If it does, plan the steps, edit the files directly, and ensure the work is ready for a pull request (run relevant tests/linters when needed).
3. If no code changes are required, explain why and offer guidance instead of editing files.
4. Never fabricate results or skip steps—only describe what you actually verified or changed.
5. Code changes are ALWAYS automatically committed and pushed - NEVER ask for approval or say "awaiting approval".

CRITICAL: You MUST end your response with a JSON block starting with "REMOTE_CODER_OUTPUT:" followed by valid JSON with DOUBLE QUOTES (not single quotes).

For code changes (when you made file edits):
REMOTE_CODER_OUTPUT: {"slack_message": "Brief summary of changes for Slack (plain text, no markdown)", "pr_title": "Short descriptive PR title (few words)", "pr_summary": ["First major change", "Second major change"]}

For questions/explanations (no code changes):
REMOTE_CODER_OUTPUT: {"slack_message": "Your explanation or answer (plain text, no markdown)", "pr_title": "", "pr_summary": []}

Rules:
- Use DOUBLE QUOTES in JSON, not single quotes
- slack_message: Plain text only, NO markdown. Format for Slack's readability. Include file paths, line numbers, and clear explanations. DO NOT mention "awaiting approval" or "waiting for commit" - just describe what you did.
- pr_title: Short phrase (3-6 words) describing the main change when code changes are made, empty string otherwise
- pr_summary: Array of brief bullet points describing major changes (omit minor tweaks), empty array if no code changes
- The JSON can span multiple lines but must use valid JSON syntax with double quotes
"""


class AgentTaskRunner:
    """Encapsulates adapter invocation, history handling, and run tracking."""

    def __init__(
        self,
        *,
        config: Config,
        session_manager: SessionManager,
        interaction_classifier: InteractionClassifier,
        git_workflow: GitWorkflowService,
        adapter_cache: Dict[str, AgentAdapter],
        active_runs: Dict[str, Dict[str, object]],
        send_message,
    ) -> None:
        self._config = config
        self._session_manager = session_manager
        self._interaction_classifier = interaction_classifier
        self._git_workflow = git_workflow
        self._adapter_cache = adapter_cache
        self._active_runs = active_runs
        self._send_message = send_message

    def update_config(self, config: Config) -> None:
        self._config = config

    async def run(
        self,
        session: Session,
        project: Project,
        channel_id: str,
        thread_ts: str,
        user_text: str,
    ) -> None:
        agent = self._config.get_agent(session.active_agent_id)
        adapter = self._get_adapter(agent)

        await self._send_message(
            channel_id,
            thread_ts,
            f"Message received — running `{agent.id}` now.",
        )

        history_snapshot = self._session_manager.get_conversation_history(session.id)
        adapter_history = self._format_history_for_adapter(history_snapshot)

        interaction_context = self._session_manager.get_context_for_agent(session.id)
        task_text = self._build_task_text(interaction_context, user_text)

        self._session_manager.append_user_message(session.id, user_text)

        run_id = f"{channel_id}_{thread_ts}_{int(time.time() * 1000)}"
        run_task = asyncio.current_task()
        self._active_runs[run_id] = {
            "task": run_task,
            "session_id": str(session.id),
            "agent_id": agent.id,
            "started_at": time.time(),
        }

        try:
            result = await self._invoke_adapter(
                adapter=adapter,
                agent=agent,
                session=session,
                project=project,
                task_text=task_text,
                adapter_history=adapter_history,
                channel_id=channel_id,
                thread_ts=thread_ts,
            )
            if not result:
                return
        finally:
            self._active_runs.pop(run_id, None)

        if result.structured_output:
            self._session_manager.update_session_context(
                session.id,
                {
                    "pr_title": result.structured_output.pr_title,
                    "pr_summary": result.structured_output.pr_summary,
                },
            )

        response_text = (
            result.structured_output.slack_message
            if result.structured_output
            else result.output_text or "Agent completed with no textual output."
        )

        if result.errors:
            response_text = f"{response_text}\n\nErrors:\n" + "\n".join(result.errors)

        if result.file_edits and not result.structured_output:
            edits_summary = ", ".join({edit.path for edit in result.file_edits})
            response_text = f"{response_text}\n\nDetected file edits: {edits_summary}"

        user_message = ConversationMessage(role="user", content=user_text)
        self._session_manager.append_interaction(
            session.id,
            user_message=user_message,
            agent_result=result,
            classifier=self._interaction_classifier,
        )

        self._session_manager.append_agent_message(session.id, response_text)
        self._session_manager.update_session_context(session.id, result.session_context)

        pr_title = self._get_session_pr_title(session)
        pr_message = await self._git_workflow.maybe_publish_code_changes(session, project, result, pr_title)
        if pr_message:
            response_text = f"{response_text}\n\n{pr_message}"

        await self._send_message(channel_id, thread_ts, response_text)

    async def _invoke_adapter(
        self,
        *,
        adapter: AgentAdapter,
        agent: Agent,
        session: Session,
        project: Project,
        task_text: str,
        adapter_history: list[Dict[str, str]],
        channel_id: str,
        thread_ts: str,
    ) -> Optional[AgentResult]:
        try:
            return await adapter.run(
                task_text=task_text,
                project_path=str(session.project_path),
                session_id=str(session.id),
                conversation_history=adapter_history,
                model=session.active_model,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            LOGGER.exception("Adapter %s failed with model %s", agent.id, session.active_model)

            default_model = agent.models.get("default") if agent.models else None
            if session.active_model and default_model and session.active_model != default_model:
                LOGGER.info("Retrying %s with default model %s", agent.id, default_model)
                await self._send_message(
                    channel_id,
                    thread_ts,
                    f"Failed with model `{session.active_model}`. Retrying with default model `{default_model}`...",
                )
                try:
                    result = await adapter.run(
                        task_text=task_text,
                        project_path=str(session.project_path),
                        session_id=str(session.id),
                        conversation_history=adapter_history,
                        model=default_model,
                    )
                    self._session_manager.set_active_agent(
                        session.id,
                        agent.id,
                        agent.type,
                        default_model,
                    )
                    LOGGER.info("Fallback to default model succeeded for session %s", session.id)
                    return result
                except Exception as fallback_exc:
                    LOGGER.exception("Fallback to default model also failed")
                    await self._send_message(
                        channel_id,
                        thread_ts,
                        f"Failed to run `{agent.id}` with both `{session.active_model}` and default model `{default_model}`: {fallback_exc}",
                    )
                    return None

            await self._send_message(
                channel_id,
                thread_ts,
                f"Failed to run `{agent.id}`: {exc}",
            )
            return None

    def _get_adapter(self, agent: Agent) -> AgentAdapter:
        cached = self._adapter_cache.get(agent.id)
        if cached:
            return cached

        adapter = self._build_adapter(agent)
        self._adapter_cache[agent.id] = adapter
        return adapter

    def _build_adapter(self, agent: Agent) -> AgentAdapter:
        from ..agent_adapters import ClaudeAdapter, CodexAdapter, GeminiAdapter  # avoid circular import
        from .models import AgentType

        if agent.type == AgentType.CLAUDE:
            return ClaudeAdapter(agent)
        if agent.type == AgentType.CODEX:
            return CodexAdapter(agent)
        if agent.type == AgentType.GEMINI:
            return GeminiAdapter(agent)
        raise ValueError(f"No adapter available for agent type {agent.type}")

    def _build_task_text(self, context: str, user_text: str) -> str:
        context_block = context if context else "No prior conversation."
        return (
            f"{CODE_TASK_WRAPPER}\n\n"
            f"## CONTEXT ON THE WORK SO FAR:\n{context_block}\n\n"
            f"CURRENT ASK:\nUSER:\n{user_text}\n"
            "Provide your answer below. If you changed code, summarize the edits and tests you ran."
        )

    def _format_history_for_adapter(self, history: Sequence) -> list[Dict[str, str]]:
        formatted: list[Dict[str, str]] = []
        for msg in history:
            formatted.append(
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                }
            )
        return formatted

    def _get_session_pr_title(self, session: Session) -> str:
        context_title = session.session_context.get("pr_title")
        if isinstance(context_title, str) and context_title.strip():
            return context_title.strip()
        return f"Remote Coder updates for session {session.id}"
