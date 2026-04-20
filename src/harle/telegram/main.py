"""Entrypoint for ``harle-telegram`` (long polling)."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher

from harle.config import load_settings
from harle.telegram.access import AccessPolicy
from harle.telegram.busy import ChatBusyGuard
from harle.telegram.client import OrchestratorClient
from harle.telegram.handlers import build_router
from harle.telegram.store import SqliteConversationStore

logger = logging.getLogger(__name__)


async def amain() -> None:
    settings = load_settings()
    token = settings.HARLE_TELEGRAM_BOT_TOKEN.strip()
    if not token:
        logger.error("HARLE_TELEGRAM_BOT_TOKEN is required")
        raise SystemExit(2)

    client = OrchestratorClient(settings.HARLE_API_URL, settings.HARLE_API_TOKEN)
    access = AccessPolicy(settings)
    store = SqliteConversationStore(settings.HARLE_TELEGRAM_STATE_PATH)
    busy_guard = ChatBusyGuard()
    await store.init()
    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_router(build_router(settings, client, access, store, busy_guard))

    logger.info(
        "harle-telegram starting (api=%s, access_policy=%s)",
        settings.HARLE_API_URL,
        settings.HARLE_TELEGRAM_ACCESS_POLICY,
    )
    try:
        await dp.start_polling(bot)
    finally:
        await store.aclose()
        await client.aclose()
        await bot.session.close()
        logger.info("harle-telegram stopped")


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        logger.info("Interrupted")


if __name__ == "__main__":
    run()
