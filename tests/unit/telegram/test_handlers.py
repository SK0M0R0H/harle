"""Tests for Telegram handlers (via Dispatcher.feed_update)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.types import Sticker

from harle.api.models import RunRequest, RunResponse
from harle.config import Settings
from harle.telegram.access import AccessPolicy
from harle.telegram.busy import ChatBusyGuard
from harle.telegram.client import OrchestratorClient
from harle.telegram.errors import ChatHTTPError
from harle.telegram.handlers import build_router
from harle.telegram.store import SqliteConversationStore

from tests.unit.telegram.conftest import RecordingSession, make_private_message, make_update


async def _init_store(tmp_path: Path) -> SqliteConversationStore:
    store = SqliteConversationStore(str(tmp_path / "telegram_state.sqlite"))
    await store.init()
    return store


@pytest.mark.asyncio
async def test_start_does_not_call_orchestrator(
    telegram_open_settings: Settings,
    recording_bot: tuple[Bot, RecordingSession],
    tmp_path: Path,
) -> None:
    bot, session = recording_bot
    orch = AsyncMock(spec=OrchestratorClient)
    orch.aclose = AsyncMock()
    access = AccessPolicy(telegram_open_settings)
    store = await _init_store(tmp_path)
    busy_guard = ChatBusyGuard()
    dp = Dispatcher()
    dp.include_router(build_router(telegram_open_settings, orch, access, store, busy_guard))  # type: ignore[arg-type]
    msg = make_private_message(text="/start")
    try:
        await dp.feed_update(bot, make_update(msg))
    finally:
        await store.aclose()
        await bot.session.close()

    orch.chat.assert_not_called()
    assert any(getattr(m, "__api_method__", None) == "sendMessage" for m in session.methods)


@pytest.mark.asyncio
async def test_help(
    recording_bot: tuple[Bot, RecordingSession],
    telegram_open_settings: Settings,
    tmp_path: Path,
) -> None:
    bot, session = recording_bot
    orch = AsyncMock(spec=OrchestratorClient)
    orch.aclose = AsyncMock()
    access = AccessPolicy(telegram_open_settings)
    store = await _init_store(tmp_path)
    busy_guard = ChatBusyGuard()
    dp = Dispatcher()
    dp.include_router(build_router(telegram_open_settings, orch, access, store, busy_guard))  # type: ignore[arg-type]
    try:
        await dp.feed_update(bot, make_update(make_private_message(text="/help")))
    finally:
        await store.aclose()
        await bot.session.close()
    orch.chat.assert_not_called()
    texts = [getattr(m, "text", "") for m in session.methods if getattr(m, "__api_method__", None) == "sendMessage"]
    assert any("Harle Telegram bot" in (t or "") for t in texts)


@pytest.mark.asyncio
async def test_allowlist_denies_before_orchestrator(
    recording_bot: tuple[Bot, RecordingSession],
    tmp_path: Path,
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
    store = await _init_store(tmp_path)
    busy_guard = ChatBusyGuard()
    dp = Dispatcher()
    dp.include_router(build_router(settings, orch, access, store, busy_guard))  # type: ignore[arg-type]
    try:
        await dp.feed_update(
            bot,
            make_update(make_private_message(text="hello world", user_id=1)),
        )
    finally:
        await store.aclose()
        await bot.session.close()
    orch.chat.assert_not_called()
    texts = [getattr(m, "text", "") for m in session.methods if getattr(m, "__api_method__", None) == "sendMessage"]
    assert any("not authorized" in (t or "").lower() for t in texts)


@pytest.mark.asyncio
async def test_text_uses_chat_with_polling(
    monkeypatch: pytest.MonkeyPatch,
    recording_bot: tuple[Bot, RecordingSession],
    telegram_open_settings: Settings,
    tmp_path: Path,
) -> None:
    bot, session = recording_bot
    orch = OrchestratorClient(telegram_open_settings.HARLE_API_URL, "")
    access = AccessPolicy(telegram_open_settings)
    store = await _init_store(tmp_path)
    busy_guard = ChatBusyGuard()

    async def fake_poll(client: object, req: object, config: object | None = None) -> RunResponse:
        return RunResponse(
            run_id="r",
            status="completed",
            result="assistant says hi",
            context="personal",
            conversation_id="conv-1",
        )

    monkeypatch.setattr("harle.telegram.handlers.chat_with_polling", fake_poll)
    dp = Dispatcher()
    dp.include_router(build_router(telegram_open_settings, orch, access, store, busy_guard))
    try:
        await dp.feed_update(bot, make_update(make_private_message(text="user question")))
        assert await store.get(1) == "conv-1"
    finally:
        await store.aclose()
        await orch.aclose()
        await bot.session.close()

    texts = [getattr(m, "text", "") for m in session.methods if getattr(m, "__api_method__", None) == "sendMessage"]
    assert any("assistant says hi" in (t or "") for t in texts)


@pytest.mark.asyncio
async def test_long_result_multiple_messages(
    monkeypatch: pytest.MonkeyPatch,
    recording_bot: tuple[Bot, RecordingSession],
    telegram_open_settings: Settings,
    tmp_path: Path,
) -> None:
    bot, session = recording_bot
    orch = OrchestratorClient(telegram_open_settings.HARLE_API_URL, "")
    access = AccessPolicy(telegram_open_settings)
    store = await _init_store(tmp_path)
    busy_guard = ChatBusyGuard()
    big = "Z" * 5000

    async def fake_poll(client: object, req: object, config: object | None = None) -> RunResponse:
        return RunResponse(run_id="r", status="completed", result=big, context="personal")

    monkeypatch.setattr("harle.telegram.handlers.chat_with_polling", fake_poll)
    dp = Dispatcher()
    dp.include_router(build_router(telegram_open_settings, orch, access, store, busy_guard))
    try:
        await dp.feed_update(bot, make_update(make_private_message(text="q")))
    finally:
        await store.aclose()
        await orch.aclose()
        await bot.session.close()

    sends = [m for m in session.methods if getattr(m, "__api_method__", None) == "sendMessage"]
    assert len(sends) >= 2


@pytest.mark.asyncio
async def test_long_error_reply_is_split_across_messages(
    monkeypatch: pytest.MonkeyPatch,
    recording_bot: tuple[Bot, RecordingSession],
    telegram_open_settings: Settings,
    tmp_path: Path,
) -> None:
    """A 5 KB orchestrator error body must arrive intact, fanned out into
    multiple Telegram messages — never truncated to a single 4096-char message."""
    bot, session = recording_bot
    orch = OrchestratorClient(telegram_open_settings.HARLE_API_URL, "")
    access = AccessPolicy(telegram_open_settings)
    store = await _init_store(tmp_path)
    busy_guard = ChatBusyGuard()
    huge_body = "B" * 5000

    async def boom(client: object, req: object, config: object | None = None) -> RunResponse:
        raise ChatHTTPError(500, huge_body)

    monkeypatch.setattr("harle.telegram.handlers.chat_with_polling", boom)
    dp = Dispatcher()
    dp.include_router(build_router(telegram_open_settings, orch, access, store, busy_guard))
    try:
        await dp.feed_update(bot, make_update(make_private_message(text="trigger error")))
    finally:
        await store.aclose()
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
    tmp_path: Path,
) -> None:
    spy = AsyncMock(side_effect=AssertionError("chat_with_polling should not run"))
    monkeypatch.setattr("harle.telegram.handlers.chat_with_polling", spy)
    bot, session = recording_bot
    orch = OrchestratorClient(telegram_open_settings.HARLE_API_URL, "")
    access = AccessPolicy(telegram_open_settings)
    store = await _init_store(tmp_path)
    busy_guard = ChatBusyGuard()
    dp = Dispatcher()
    dp.include_router(build_router(telegram_open_settings, orch, access, store, busy_guard))
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
        await store.aclose()
        await orch.aclose()
        await bot.session.close()

    spy.assert_not_called()
    texts = [getattr(m, "text", "") for m in session.methods if getattr(m, "__api_method__", None) == "sendMessage"]
    assert any("content type" in (t or "").lower() for t in texts)


@pytest.mark.asyncio
async def test_new_command_clears_conversation(
    monkeypatch: pytest.MonkeyPatch,
    recording_bot: tuple[Bot, RecordingSession],
    telegram_open_settings: Settings,
    tmp_path: Path,
) -> None:
    bot, _session = recording_bot
    orch = OrchestratorClient(telegram_open_settings.HARLE_API_URL, "")
    access = AccessPolicy(telegram_open_settings)
    store = await _init_store(tmp_path)
    busy_guard = ChatBusyGuard()
    await store.set(1, "conv-existing")

    captured_conversation_ids: list[str | None] = []

    async def fake_poll(client: object, req: RunRequest, config: object | None = None) -> RunResponse:
        captured_conversation_ids.append(req.conversation_id)
        return RunResponse(run_id="r", status="completed", result="ok", context="personal")

    monkeypatch.setattr("harle.telegram.handlers.chat_with_polling", fake_poll)
    dp = Dispatcher()
    dp.include_router(build_router(telegram_open_settings, orch, access, store, busy_guard))
    try:
        await dp.feed_update(bot, make_update(make_private_message(text="/new")))
        await dp.feed_update(bot, make_update(make_private_message(text="next turn")))
    finally:
        await store.aclose()
        await orch.aclose()
        await bot.session.close()

    assert captured_conversation_ids == [None]


@pytest.mark.asyncio
async def test_id_command_reports_current_conversation(
    recording_bot: tuple[Bot, RecordingSession],
    telegram_open_settings: Settings,
    tmp_path: Path,
) -> None:
    bot, session = recording_bot
    orch = OrchestratorClient(telegram_open_settings.HARLE_API_URL, "")
    access = AccessPolicy(telegram_open_settings)
    store = await _init_store(tmp_path)
    busy_guard = ChatBusyGuard()
    await store.set(1, "conv-123")
    dp = Dispatcher()
    dp.include_router(build_router(telegram_open_settings, orch, access, store, busy_guard))
    try:
        await dp.feed_update(bot, make_update(make_private_message(text="/id")))
    finally:
        await store.aclose()
        await orch.aclose()
        await bot.session.close()

    texts = [getattr(m, "text", "") for m in session.methods if getattr(m, "__api_method__", None) == "sendMessage"]
    assert any("conv-123" in (t or "") for t in texts)


@pytest.mark.asyncio
async def test_rejects_second_message_while_first_is_inflight(
    monkeypatch: pytest.MonkeyPatch,
    recording_bot: tuple[Bot, RecordingSession],
    telegram_open_settings: Settings,
    tmp_path: Path,
) -> None:
    bot, session = recording_bot
    orch = OrchestratorClient(telegram_open_settings.HARLE_API_URL, "")
    access = AccessPolicy(telegram_open_settings)
    store = await _init_store(tmp_path)
    busy_guard = ChatBusyGuard()

    gate = asyncio.Event()
    calls = 0

    async def fake_poll(client: object, req: RunRequest, config: object | None = None) -> RunResponse:
        nonlocal calls
        calls += 1
        await gate.wait()
        return RunResponse(run_id="r", status="completed", result="done", context="personal")

    monkeypatch.setattr("harle.telegram.handlers.chat_with_polling", fake_poll)
    dp = Dispatcher()
    dp.include_router(build_router(telegram_open_settings, orch, access, store, busy_guard))
    try:
        first_task = asyncio.create_task(dp.feed_update(bot, make_update(make_private_message(text="first"))))
        await asyncio.sleep(0.01)
        await dp.feed_update(bot, make_update(make_private_message(text="second")))
        gate.set()
        await first_task
    finally:
        await store.aclose()
        await orch.aclose()
        await bot.session.close()

    assert calls == 1
    texts = [getattr(m, "text", "") for m in session.methods if getattr(m, "__api_method__", None) == "sendMessage"]
    assert any("please wait" in (t or "").lower() for t in texts)


@pytest.mark.asyncio
async def test_new_during_inflight_does_not_restore_old_conversation_id(
    monkeypatch: pytest.MonkeyPatch,
    recording_bot: tuple[Bot, RecordingSession],
    telegram_open_settings: Settings,
    tmp_path: Path,
) -> None:
    """``/new`` while ``/chat`` is in flight must not let the late response repopulate the store."""
    bot, _session = recording_bot
    orch = OrchestratorClient(telegram_open_settings.HARLE_API_URL, "")
    access = AccessPolicy(telegram_open_settings)
    store = await _init_store(tmp_path)
    busy_guard = ChatBusyGuard()
    await store.set(1, "conv-old")

    gate = asyncio.Event()

    async def fake_poll(client: object, req: RunRequest, config: object | None = None) -> RunResponse:
        await gate.wait()
        return RunResponse(
            run_id="r",
            status="completed",
            result="stale reply",
            context="personal",
            conversation_id="conv-from-stale-turn",
        )

    monkeypatch.setattr("harle.telegram.handlers.chat_with_polling", fake_poll)
    dp = Dispatcher()
    dp.include_router(build_router(telegram_open_settings, orch, access, store, busy_guard))
    try:
        first_task = asyncio.create_task(
            dp.feed_update(bot, make_update(make_private_message(text="long running"))),
        )
        await asyncio.sleep(0.05)
        await dp.feed_update(bot, make_update(make_private_message(text="/new")))
        gate.set()
        await first_task
        assert await store.get(1) is None
    finally:
        await store.aclose()
        await orch.aclose()
        await bot.session.close()


@pytest.mark.asyncio
async def test_markdown_v2_falls_back_to_plain_text_on_parse_error(
    monkeypatch: pytest.MonkeyPatch,
    recording_bot: tuple[Bot, RecordingSession],
    telegram_open_settings: Settings,
    tmp_path: Path,
) -> None:
    bot, session = recording_bot
    session.fail_markdown_v2 = True
    orch = OrchestratorClient(telegram_open_settings.HARLE_API_URL, "")
    access = AccessPolicy(telegram_open_settings)
    store = await _init_store(tmp_path)
    busy_guard = ChatBusyGuard()

    async def fake_poll(client: object, req: RunRequest, config: object | None = None) -> RunResponse:
        return RunResponse(run_id="r", status="completed", result="*bold*", context="personal")

    monkeypatch.setattr("harle.telegram.handlers.chat_with_polling", fake_poll)
    dp = Dispatcher()
    dp.include_router(build_router(telegram_open_settings, orch, access, store, busy_guard))
    try:
        await dp.feed_update(bot, make_update(make_private_message(text="hello")))
    finally:
        await store.aclose()
        await orch.aclose()
        await bot.session.close()

    sends = [m for m in session.methods if getattr(m, "__api_method__", None) == "sendMessage"]
    assert any(getattr(m, "parse_mode", None) in ("MarkdownV2", ParseMode.MARKDOWN_V2) for m in sends)
    assert any(getattr(m, "parse_mode", None) not in ("MarkdownV2", ParseMode.MARKDOWN_V2) for m in sends)


@pytest.mark.asyncio
async def test_typing_indicator_sent_during_turn(
    monkeypatch: pytest.MonkeyPatch,
    recording_bot: tuple[Bot, RecordingSession],
    telegram_open_settings: Settings,
    tmp_path: Path,
) -> None:
    bot, session = recording_bot
    orch = OrchestratorClient(telegram_open_settings.HARLE_API_URL, "")
    access = AccessPolicy(telegram_open_settings)
    store = await _init_store(tmp_path)
    busy_guard = ChatBusyGuard()

    async def fake_poll(client: object, req: RunRequest, config: object | None = None) -> RunResponse:
        await asyncio.sleep(0.05)
        return RunResponse(run_id="r", status="completed", result="ok", context="personal")

    monkeypatch.setattr("harle.telegram.handlers.chat_with_polling", fake_poll)
    dp = Dispatcher()
    dp.include_router(build_router(telegram_open_settings, orch, access, store, busy_guard))
    try:
        await dp.feed_update(bot, make_update(make_private_message(text="hello")))
    finally:
        await store.aclose()
        await orch.aclose()
        await bot.session.close()

    assert any(getattr(m, "__api_method__", None) == "sendChatAction" for m in session.methods)
