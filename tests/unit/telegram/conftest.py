"""Shared helpers for Telegram bot unit tests."""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods.base import TelegramType
from aiogram.types import Chat, Message, Update, User
from aiogram.enums import ChatType

from harle.config import Settings


@pytest.fixture
def telegram_open_settings() -> Settings:
    return Settings(
        HARLE_TELEGRAM_ACCESS_POLICY="open",
        HARLE_API_URL="http://127.0.0.1:9",
    )


def make_private_message(*, text: str | None, user_id: int = 1, sticker: Any | None = None) -> Message:
    user = User(id=user_id, is_bot=False, first_name="Test")
    chat = Chat(id=user_id, type=ChatType.PRIVATE)
    kwargs: dict[str, Any] = {
        "message_id": 1,
        "date": dt.datetime.now(dt.timezone.utc),
        "chat": chat,
        "from_user": user,
    }
    if text is not None:
        kwargs["text"] = text
    if sticker is not None:
        kwargs["sticker"] = sticker
    return Message(**kwargs)


def make_update(message: Message) -> Update:
    return Update(update_id=1, message=message)


class RecordingSession(BaseSession):
    """Captures outgoing Telegram API methods and returns minimal success payloads."""

    def __init__(self) -> None:
        super().__init__()
        self.methods: list[Any] = []
        self.fail_markdown_v2 = False

    async def close(self) -> None:
        pass

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        yield b""

    async def make_request(
        self,
        bot: Bot,
        method: Any,
        timeout: int | None = None,
    ) -> TelegramType:
        self.methods.append(method)
        api = method.__api_method__
        if api == "sendMessage":
            parse_mode = getattr(method, "parse_mode", None)
            if self.fail_markdown_v2 and parse_mode in ("MarkdownV2", ParseMode.MARKDOWN_V2):
                raise TelegramBadRequest(method=method, message="can't parse entities")
        if api == "sendMessage":
            from aiogram.types import Message as OutMessage

            data = method.model_dump(mode="python", exclude_unset=True)
            chat_id = data.get("chat_id")
            chat = Chat(id=int(chat_id), type=ChatType.PRIVATE)
            return OutMessage(
                message_id=len(self.methods) + 100,
                date=dt.datetime.now(dt.timezone.utc),
                chat=chat,
                text=data.get("text"),
            )
        return True  # pragma: no cover


@pytest.fixture
def recording_bot() -> tuple[Bot, RecordingSession]:
    session = RecordingSession()
    bot = Bot(token="1:TEST-TOKEN", session=session)
    return bot, session
