"""Telegram message and command handlers (Stage 1)."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from pydantic import ValidationError

from harle.api.models import RunRequest
from harle.config import Settings
from harle.telegram.access import AccessPolicy
from harle.telegram.client import OrchestratorClient
from harle.telegram.errors import ChatHTTPError, ChatProcessingLost, ChatServerTimeout, ChatUnreachable
from harle.telegram.middleware import PrivateChatOnlyMiddleware, TelegramContextMiddleware
from harle.telegram.processing import chat_with_polling
from harle.telegram.transport import error_reply_for, split_for_telegram, unsupported_content_reply

logger = logging.getLogger(__name__)


def build_router(settings: Settings, client: OrchestratorClient, access: AccessPolicy) -> Router:
    """Create a router with middleware and Stage 1 handlers."""
    router = Router(name="telegram_stage1")
    router.message.middleware(PrivateChatOnlyMiddleware())
    router.message.middleware(TelegramContextMiddleware(settings, client, access))

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
            "Each message starts a fresh conversation (no memory between messages in this version)."
        )

    @router.message(Command("help"))
    async def cmd_help(message: Message, access_policy: AccessPolicy) -> None:
        uid = message.from_user.id if message.from_user else None
        if not access_policy.is_allowed(uid):
            await message.answer(access_policy.refusal_message())
            return
        await message.answer(
            "Harle Telegram bot (Stage 1)\n\n"
            "/start — welcome and what this bot does\n"
            "/help — this message\n\n"
            "Send plain text to talk to the assistant. "
            "Photos, voice, and other attachments are not supported yet."
        )

    @router.message(F.text)
    async def on_text(
        message: Message,
        orchestrator_client: OrchestratorClient,
        access_policy: AccessPolicy,
    ) -> None:
        uid = message.from_user.id if message.from_user else None
        if not access_policy.is_allowed(uid):
            await message.answer(access_policy.refusal_message())
            return

        text = (message.text or "").strip()
        if not text:
            await message.answer("Please send a non-empty text message.")
            return

        # Stage 1: send the orchestrator's default ``context`` (currently "personal").
        # Per-message context selection is the orchestrator/role's responsibility, not the bot's.
        try:
            run_request = RunRequest(message=text, conversation_id=None)
        except ValidationError:
            await message.answer("That message could not be sent to Harle (validation error).")
            return

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

        if response.status == "failed":
            for chunk in split_for_telegram(response.result or "The assistant reported a failure with no details."):
                await message.answer(chunk)
            return

        for chunk in split_for_telegram(response.result):
            await message.answer(chunk)

    @router.message(~F.text)
    async def on_non_text(message: Message, access_policy: AccessPolicy) -> None:
        uid = message.from_user.id if message.from_user else None
        if not access_policy.is_allowed(uid):
            await message.answer(access_policy.refusal_message())
            return
        await message.answer(unsupported_content_reply())

    return router
