"""Tests for Telegram handlers (via Dispatcher.feed_update)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import Sticker

from harle.api.models import RunResponse
from harle.config import Settings
from harle.telegram.access import AccessPolicy
from harle.telegram.client import OrchestratorClient
from harle.telegram.errors import ChatHTTPError
from harle.telegram.handlers import build_router

from tests.unit.telegram.conftest import RecordingSession, make_private_message, make_update


@pytest.mark.asyncio
async def test_start_does_not_call_orchestrator(
    telegram_open_settings: Settings,
    recording_bot: tuple[Bot, RecordingSession],
) -> None:
    bot, session = recording_bot
    orch = AsyncMock(spec=OrchestratorClient)
    orch.aclose = AsyncMock()
    access = AccessPolicy(telegram_open_settings)
    dp = Dispatcher()
    dp.include_router(build_router(telegram_open_settings, orch, access))  # type: ignore[arg-type]
    msg = make_private_message(text="/start")
    try:
        await dp.feed_update(bot, make_update(msg))
    finally:
        await bot.session.close()

    orch.chat.assert_not_called()
    assert any(getattr(m, "__api_method__", None) == "sendMessage" for m in session.methods)


@pytest.mark.asyncio
async def test_help(
    recording_bot: tuple[Bot, RecordingSession],
    telegram_open_settings: Settings,
) -> None:
    bot, session = recording_bot
    orch = AsyncMock(spec=OrchestratorClient)
    orch.aclose = AsyncMock()
    access = AccessPolicy(telegram_open_settings)
    dp = Dispatcher()
    dp.include_router(build_router(telegram_open_settings, orch, access))  # type: ignore[arg-type]
    try:
        await dp.feed_update(bot, make_update(make_private_message(text="/help")))
    finally:
        await bot.session.close()
    orch.chat.assert_not_called()
    texts = [getattr(m, "text", "") for m in session.methods if getattr(m, "__api_method__", None) == "sendMessage"]
    assert any("Harle Telegram bot" in (t or "") for t in texts)


@pytest.mark.asyncio
async def test_allowlist_denies_before_orchestrator(
    recording_bot: tuple[Bot, RecordingSession],
) -> None:
    settings = Settings(
        HARLE_TELEGRAM_ACCESS_POLICY="allowlist",
        HARLE_TELEGRAM_ALLOWED_USER_IDS="99",
        HARLE_API_URL="http://127.0.0.1:9",
    )
    bot, session = recording_bot
    orch = AsyncMock(spec=OrchestratorClient)
    orch.aclose = AsyncMock()
    access = AccessPolicy(settings)
    dp = Dispatcher()
    dp.include_router(build_router(settings, orch, access))  # type: ignore[arg-type]
    try:
        await dp.feed_update(
            bot,
            make_update(make_private_message(text="hello world", user_id=1)),
        )
    finally:
        await bot.session.close()
    orch.chat.assert_not_called()
    texts = [getattr(m, "text", "") for m in session.methods if getattr(m, "__api_method__", None) == "sendMessage"]
    assert any("not authorized" in (t or "").lower() for t in texts)


@pytest.mark.asyncio
async def test_text_uses_chat_with_polling(
    monkeypatch: pytest.MonkeyPatch,
    recording_bot: tuple[Bot, RecordingSession],
    telegram_open_settings: Settings,
) -> None:
    bot, session = recording_bot
    orch = OrchestratorClient(telegram_open_settings.HARLE_API_URL, "")
    access = AccessPolicy(telegram_open_settings)

    async def fake_poll(client: object, req: object, config: object | None = None) -> RunResponse:
        return RunResponse(
            run_id="r",
            status="completed",
            result="assistant says hi",
            context="personal",
        )

    monkeypatch.setattr("harle.telegram.handlers.chat_with_polling", fake_poll)
    dp = Dispatcher()
    dp.include_router(build_router(telegram_open_settings, orch, access))
    try:
        await dp.feed_update(bot, make_update(make_private_message(text="user question")))
    finally:
        await orch.aclose()
        await bot.session.close()

    texts = [getattr(m, "text", "") for m in session.methods if getattr(m, "__api_method__", None) == "sendMessage"]
    assert any("assistant says hi" in (t or "") for t in texts)


@pytest.mark.asyncio
async def test_long_result_multiple_messages(
    monkeypatch: pytest.MonkeyPatch,
    recording_bot: tuple[Bot, RecordingSession],
    telegram_open_settings: Settings,
) -> None:
    bot, session = recording_bot
    orch = OrchestratorClient(telegram_open_settings.HARLE_API_URL, "")
    access = AccessPolicy(telegram_open_settings)
    big = "Z" * 5000

    async def fake_poll(client: object, req: object, config: object | None = None) -> RunResponse:
        return RunResponse(run_id="r", status="completed", result=big, context="personal")

    monkeypatch.setattr("harle.telegram.handlers.chat_with_polling", fake_poll)
    dp = Dispatcher()
    dp.include_router(build_router(telegram_open_settings, orch, access))
    try:
        await dp.feed_update(bot, make_update(make_private_message(text="q")))
    finally:
        await orch.aclose()
        await bot.session.close()

    sends = [m for m in session.methods if getattr(m, "__api_method__", None) == "sendMessage"]
    assert len(sends) >= 2


@pytest.mark.asyncio
async def test_long_error_reply_is_split_across_messages(
    monkeypatch: pytest.MonkeyPatch,
    recording_bot: tuple[Bot, RecordingSession],
    telegram_open_settings: Settings,
) -> None:
    """A 5 KB orchestrator error body must arrive intact, fanned out into
    multiple Telegram messages — never truncated to a single 4096-char message."""
    bot, session = recording_bot
    orch = OrchestratorClient(telegram_open_settings.HARLE_API_URL, "")
    access = AccessPolicy(telegram_open_settings)
    huge_body = "B" * 5000

    async def boom(client: object, req: object, config: object | None = None) -> RunResponse:
        raise ChatHTTPError(500, huge_body)

    monkeypatch.setattr("harle.telegram.handlers.chat_with_polling", boom)
    dp = Dispatcher()
    dp.include_router(build_router(telegram_open_settings, orch, access))
    try:
        await dp.feed_update(bot, make_update(make_private_message(text="trigger error")))
    finally:
        await orch.aclose()
        await bot.session.close()

    sends = [m for m in session.methods if getattr(m, "__api_method__", None) == "sendMessage"]
    assert len(sends) >= 2, "long error reply should fan out across multiple messages"
    combined = "".join((getattr(m, "text", "") or "") for m in sends)
    assert huge_body in combined, "no part of the orchestrator body should be dropped"


@pytest.mark.asyncio
async def test_sticker_no_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
    recording_bot: tuple[Bot, RecordingSession],
    telegram_open_settings: Settings,
) -> None:
    spy = AsyncMock(side_effect=AssertionError("chat_with_polling should not run"))
    monkeypatch.setattr("harle.telegram.handlers.chat_with_polling", spy)
    bot, session = recording_bot
    orch = OrchestratorClient(telegram_open_settings.HARLE_API_URL, "")
    access = AccessPolicy(telegram_open_settings)
    dp = Dispatcher()
    dp.include_router(build_router(telegram_open_settings, orch, access))
    sticker = Sticker(
        file_id="f",
        file_unique_id="u",
        type="regular",
        width=1,
        height=1,
        is_animated=False,
        is_video=False,
    )
    msg = make_private_message(text=None, sticker=sticker)
    try:
        await dp.feed_update(bot, make_update(msg))
    finally:
        await orch.aclose()
        await bot.session.close()

    spy.assert_not_called()
    texts = [getattr(m, "text", "") for m in session.methods if getattr(m, "__api_method__", None) == "sendMessage"]
    assert any("content type" in (t or "").lower() for t in texts)
