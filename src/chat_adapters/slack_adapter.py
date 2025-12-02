"""Slack adapter using the official Slack SDK."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from slack_sdk.errors import SlackApiError
from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web.async_client import AsyncWebClient

from .i_chat_adapter import IChatAdapter
from ..errors import SlackError
from ..router import Router

LOGGER = logging.getLogger(__name__)


class SlackAdapter(IChatAdapter):
    def __init__(
        self,
        bot_token: str,
        app_token: str,
        allowed_user_id: str,
        router: Router,
    ) -> None:
        self._web_client = AsyncWebClient(token=bot_token)
        self._client = SocketModeClient(app_token=app_token, web_client=self._web_client)
        self._router = router
        self._allowed_user_id = allowed_user_id
        self._stop_event = asyncio.Event()
        self._client.socket_mode_request_listeners.append(self._handle_socket_request)

    async def send_message(self, channel: str, thread_ts: str, text: str) -> None:
        try:
            await self._web_client.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)
        except SlackApiError as exc:
            raise SlackError(f"Failed to send Slack message: {exc}") from exc

    async def start(self) -> None:
        LOGGER.info("Connecting to Slack via Socket Mode")
        await self._client.connect()
        await self._stop_event.wait()

    async def stop(self) -> None:
        if not self._stop_event.is_set():
            self._stop_event.set()
        await self._client.close()

    async def _handle_socket_request(
        self,
        client: SocketModeClient,
        req: SocketModeRequest,
    ) -> None:
        if req.type != "events_api":
            await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
            return

        payload = req.payload or {}
        event = payload.get("event", {})
        await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

        user_id = event.get("user")
        if user_id != self._allowed_user_id:
            LOGGER.debug("Ignoring message from unauthorized user %s", user_id)
            return

        event_type = event.get("type")
        subtype = event.get("subtype")
        if event_type != "message" or subtype == "bot_message":
            LOGGER.debug("Ignoring Slack event type %s with subtype %s", event_type, subtype)
            return

        await self._router.handle_message(event)
