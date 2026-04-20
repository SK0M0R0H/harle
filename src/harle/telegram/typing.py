"""Typing indicator loop helpers."""

from __future__ import annotations

import asyncio

from aiogram import Bot

_TYPING_INTERVAL_SECONDS = 4.0


async def typing_loop(bot: Bot, chat_id: int, stop_event: asyncio.Event) -> None:
    """Send periodic Telegram typing actions until ``stop_event`` is set."""
    while not stop_event.is_set():
        await bot.send_chat_action(chat_id=chat_id, action="typing")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_TYPING_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            continue


__all__ = ["typing_loop"]
