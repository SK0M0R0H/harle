"""Telegram message and command handlers (Stage 2)."""

from __future__ import annotations

import logging
import asyncio

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from pydantic import ValidationError

from harle.api.models import RunRequest
from harle.config import Settings
from harle.telegram.access import AccessPolicy
from harle.telegram.busy import ChatBusyGuard
from harle.telegram.client import OrchestratorClient
from harle.telegram.errors import ChatHTTPError, ChatProcessingLost, ChatServerTimeout, ChatUnreachable
from harle.telegram.middleware import PrivateChatOnlyMiddleware, TelegramContextMiddleware
from harle.telegram.processing import chat_with_polling
from harle.telegram.render import to_markdown_v2
from harle.telegram.store import SqliteConversationStore
from harle.telegram.transport import (
    error_reply_for,
    send_rendered_reply,
    split_for_telegram,
    unsupported_content_reply,
)
from harle.telegram.typing import typing_loop

logger = logging.getLogger(__name__)


_BUSY_MESSAGE = "Please wait for the current reply to finish, then send your next message."


def build_router(
    settings: Settings,
    client: OrchestratorClient,
    access: AccessPolicy,
    store: SqliteConversationStore,
    busy_guard: ChatBusyGuard,
) -> Router:
    """Create a router with middleware and Stage 2 handlers."""
    router = Router(name="telegram_stage2")
    router.message.middleware(PrivateChatOnlyMiddleware())
    router.message.middleware(TelegramContextMiddleware(settings, client, access, store, busy_guard))

    @router.message(CommandStart())
    async def cmd_start(message: Message, access_policy: AccessPolicy) -> None:
        uid = message.from_user.id if message.from_user else None
        if not access_policy.is_allowed(uid):
            await message.answer(access_policy.refusal_message())
            return
        await message.answer(
            "Welcome to Harle. Send me any text message and I will forward it to your "
            "assistant on the Harle server and reply with the answer.\n\n"
            "Commands:\n"
            "/help — list commands\n\n"
            "/new — start a fresh conversation\n"
            "/id — show your current conversation id"
        )

    @router.message(Command("help"))
    async def cmd_help(message: Message, access_policy: AccessPolicy) -> None:
        uid = message.from_user.id if message.from_user else None
        if not access_policy.is_allowed(uid):
            await message.answer(access_policy.refusal_message())
            return
        await message.answer(
            "Harle Telegram bot (Stage 2)\n\n"
            "/start — welcome and what this bot does\n"
            "/help — this message\n\n"
            "/new — start a fresh conversation\n"
            "/id — show current conversation id\n\n"
            "Send plain text to talk to the assistant. "
            "Photos, voice, and other attachments are not supported yet."
        )

    @router.message(Command("new"))
    async def cmd_new(
        message: Message,
        access_policy: AccessPolicy,
        store: SqliteConversationStore,
    ) -> None:
        uid = message.from_user.id if message.from_user else None
        if not access_policy.is_allowed(uid):
            await message.answer(access_policy.refusal_message())
            return
        await store.clear(message.chat.id)
        await message.answer("Started a new conversation. Your next message begins fresh.")

    @router.message(Command("id"))
    async def cmd_id(
        message: Message,
        access_policy: AccessPolicy,
        store: SqliteConversationStore,
    ) -> None:
        uid = message.from_user.id if message.from_user else None
        if not access_policy.is_allowed(uid):
            await message.answer(access_policy.refusal_message())
            return
        conversation_id = await store.get(message.chat.id)
        if conversation_id:
            await message.answer(f"conversation_id: {conversation_id}")
            return
        await message.answer("No active conversation yet.")

    @router.message(F.text)
    async def on_text(
        message: Message,
        orchestrator_client: OrchestratorClient,
        access_policy: AccessPolicy,
        store: SqliteConversationStore,
        busy_guard: ChatBusyGuard,
    ) -> None:
        uid = message.from_user.id if message.from_user else None
        if not access_policy.is_allowed(uid):
            await message.answer(access_policy.refusal_message())
            return

        chat_id = message.chat.id
        if not await busy_guard.try_acquire(chat_id):
            await message.answer(_BUSY_MESSAGE)
            return

        text = (message.text or "").strip()
        if not text:
            await message.answer("Please send a non-empty text message.")
            await busy_guard.release(chat_id)
            return

        try:
            conversation_id = await store.get(chat_id)
            run_request = RunRequest(message=text, conversation_id=conversation_id)
        except ValidationError:
            await message.answer("That message could not be sent to Harle (validation error).")
            await busy_guard.release(chat_id)
            return

        typing_stop = asyncio.Event()
        typing_task = asyncio.create_task(typing_loop(message.bot, chat_id, typing_stop))
        try:
            response = await chat_with_polling(orchestrator_client, run_request)
        except (ChatServerTimeout, ChatUnreachable, ChatProcessingLost, ChatHTTPError) as exc:
            logger.warning(
                "Orchestrator error for user_id=%s request_id=%s: %s",
                uid, exc.request_id, exc, exc_info=True,
            )
            for chunk in split_for_telegram(error_reply_for(exc)):
                await message.answer(chunk)
            return
        except Exception as exc:  # noqa: BLE001 — last-resort user-facing fallback
            logger.exception("Unexpected error for user_id=%s", uid)
            for chunk in split_for_telegram(error_reply_for(exc)):
                await message.answer(chunk)
            return
        finally:
            typing_stop.set()
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                # typing_loop can raise Telegram API errors (network, blocked chat, etc.).
                # Swallow here so busy_guard is always released; the user already got a reply
                # or an error from chat_with_polling above.
                logger.warning(
                    "Typing indicator task ended with error for chat_id=%s: %s",
                    chat_id,
                    exc,
                    exc_info=True,
                )
            finally:
                await busy_guard.release(chat_id)

        if response.conversation_id:
            await store.set(chat_id, response.conversation_id)

        plain_result = response.result or "The assistant returned an empty response."
        if response.status == "failed":
            for chunk in split_for_telegram(plain_result):
                await message.answer(chunk)
            return

        await send_rendered_reply(
            message,
            markdown_v2=to_markdown_v2(plain_result),
            plain_text=plain_result,
        )

    @router.message(~F.text)
    async def on_non_text(message: Message, access_policy: AccessPolicy) -> None:
        uid = message.from_user.id if message.from_user else None
        if not access_policy.is_allowed(uid):
            await message.answer(access_policy.refusal_message())
            return
        await message.answer(unsupported_content_reply())

    return router
