"""Inject orchestrator client and settings into handler ``data``."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import Message, TelegramObject

from harle.config import Settings
from harle.telegram.access import AccessPolicy
from harle.telegram.busy import ChatBusyGuard
from harle.telegram.client import OrchestratorClient
from harle.telegram.store import SqliteConversationStore


class TelegramContextMiddleware(BaseMiddleware):
    """Attach ``settings``, ``orchestrator_client``, and ``access_policy`` to handler data."""

    def __init__(
        self,
        settings: Settings,
        client: OrchestratorClient,
        access: AccessPolicy,
        store: SqliteConversationStore,
        busy_guard: ChatBusyGuard,
    ) -> None:
        self._settings = settings
        self._client = client
        self._access = access
        self._store = store
        self._busy_guard = busy_guard

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["settings"] = self._settings
        data["orchestrator_client"] = self._client
        data["access_policy"] = self._access
        data["store"] = self._store
        data["busy_guard"] = self._busy_guard
        return await handler(event, data)


class PrivateChatOnlyMiddleware(BaseMiddleware):
    """Reply once for non-private chats and skip the rest of the stack."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            if event.chat.type != ChatType.PRIVATE:
                await event.answer(
                    "I only work in private direct messages for now. "
                    "Open a private chat with this bot and try again."
                )
                return None
        return await handler(event, data)
