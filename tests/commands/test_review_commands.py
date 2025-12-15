"""Tests for ReviewCommandHandler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.commands.parser import ParsedCommand
from src.core.commands.review import ReviewCommandHandler
from src.core.errors import GitHubError, SessionNotFound
from src.github.client import PRComment
from src.core.models import PullRequestRef


class TestReviewCommands:
    """Review command handler tests."""

    @pytest.fixture
    def github_manager(self):
        manager = MagicMock()
        manager.is_configured.return_value = True
        manager.get_unresolved_comments = AsyncMock(return_value=[])
        return manager

    @pytest.fixture
    def session_manager(self):
        manager = MagicMock()
        manager.get_pr_ref.return_value = PullRequestRef(
            project_id="test-project",
            session_id="session",
            number=1,
            url="https://example.com/pr/1",
            head_branch="remote",
            base_branch="main",
        )
        return manager

    @pytest.fixture
    def handler(self, session_manager, github_manager, mock_send_message):
        build_prompt = MagicMock(return_value="prompt")
        execute_agent = AsyncMock()
        return ReviewCommandHandler(
            session_manager=session_manager,
            github_manager=github_manager,
            build_review_prompt=build_prompt,
            execute_agent_task=execute_agent,
            send_message=mock_send_message,
        )

    @pytest.mark.asyncio
    async def test_handle_review_requires_github(self, handler, command_context, github_manager, mock_send_message):
        command_context = command_context
        command_context.project.github = None  # type: ignore[attr-defined]

        command = ParsedCommand(name="review", args=[])
        await handler.handle_review(command, command_context)

        assert "no GitHub configuration" in mock_send_message.messages[-1]["text"]

    @pytest.mark.asyncio
    async def test_handle_review_requires_token(self, handler, command_context, github_manager, mock_send_message):
        github_manager.is_configured.return_value = False

        command = ParsedCommand(name="review", args=[])
        await handler.handle_review(command, command_context)

        assert "GitHub token is not configured" in mock_send_message.messages[-1]["text"]

    @pytest.mark.asyncio
    async def test_handle_review_no_pr(self, handler, command_context, session_manager, mock_send_message):
        session_manager.get_pr_ref.side_effect = SessionNotFound("missing")

        command = ParsedCommand(name="review", args=[])
        await handler.handle_review(command, command_context)

        assert "No pull request exists yet" in mock_send_message.messages[-1]["text"]

    @pytest.mark.asyncio
    async def test_handle_review_no_comments(self, handler, command_context, mock_send_message):
        command = ParsedCommand(name="review", args=[])
        await handler.handle_review(command, command_context)

        assert "No unresolved review threads" in mock_send_message.messages[-1]["text"]

    @pytest.mark.asyncio
    async def test_handle_review_with_comments_runs_agent(
        self,
        handler,
        command_context,
        github_manager,
        mock_send_message,
    ):
        github_manager.get_unresolved_comments.return_value = [
            PRComment(
                author="reviewer",
                body="Please fix this",
                url="https://example.com/comment",
                path="src/main.py",
                position="42",
            )
        ]
        command = ParsedCommand(name="review", args=[])

        await handler.handle_review(command, command_context)

        assert "Unresolved review comments" in mock_send_message.messages[-1]["text"]
        handler._execute_agent_task.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_handle_review_github_error(self, handler, command_context, github_manager, mock_send_message):
        github_manager.get_unresolved_comments.side_effect = GitHubError("fail")
        command = ParsedCommand(name="review", args=[])

        await handler.handle_review(command, command_context)

        assert "Unable to fetch PR comments" in mock_send_message.messages[-1]["text"]
