"""POST /chat liveness via GET /processing/{request_id} (aligned with harle-cli)."""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass, replace

from harle.api.models import RunRequest, RunResponse
from harle.telegram.client import OrchestratorClient
from harle.telegram.errors import (
    ChatError,
    ChatHTTPError,
    ChatProcessingLost,
    ChatServerTimeout,
    ChatUnreachable,
)

_POST_CANCEL_DRAIN_SECONDS = 30.0


@dataclass(frozen=True)
class PollConfig:
    ping_interval: float = 15.0
    max_missed_pings: int = 3
    grace_period: float = 5.0
    max_wait_seconds: float | None = None


def poll_config_from_environment() -> PollConfig:
    """Overlay ``HARLE_CHAT_*`` on defaults (same semantics as Go ``PollConfigFromEnvironment``)."""
    cfg = PollConfig()
    if s := os.getenv("HARLE_CHAT_PING_INTERVAL_SECONDS", "").strip():
        if (n := _int_positive(s)) is not None:
            cfg = replace(cfg, ping_interval=float(n))
    if s := os.getenv("HARLE_CHAT_GRACE_PERIOD_SECONDS", "").strip():
        if (n := _int_non_negative(s)) is not None:
            cfg = replace(cfg, grace_period=float(n))
    if s := os.getenv("HARLE_CHAT_MAX_MISSED_PINGS", "").strip():
        if (n := _int_positive(s)) is not None:
            cfg = replace(cfg, max_missed_pings=n)
    if s := os.getenv("HARLE_CHAT_MAX_WAIT_SECONDS", "").strip():
        if (n := _int_positive(s)) is not None:
            cfg = replace(cfg, max_wait_seconds=float(n))
    return cfg


def resolve_poll_config(config: PollConfig | None) -> PollConfig:
    """Effective :class:`PollConfig` for a single :func:`chat_with_polling` call.

    When *config* is ``None``, reads ``HARLE_CHAT_*`` from the environment (each
    call). Then applies guards so invalid values cannot disable polling or
    negative grace periods.
    """
    cfg = poll_config_from_environment() if config is None else config
    if cfg.ping_interval <= 0:
        cfg = replace(cfg, ping_interval=15.0)
    if cfg.max_missed_pings <= 0:
        cfg = replace(cfg, max_missed_pings=3)
    if cfg.grace_period < 0:
        cfg = replace(cfg, grace_period=0.0)
    return cfg


def _int_positive(s: str) -> int | None:
    try:
        n = int(s)
        return n if n > 0 else None
    except ValueError:
        return None


def _int_non_negative(s: str) -> int | None:
    try:
        n = int(s)
        return n if n >= 0 else None
    except ValueError:
        return None


async def chat_with_polling(
    client: OrchestratorClient,
    request: RunRequest,
    *,
    config: PollConfig | None = None,
) -> RunResponse:
    """Run ``POST /chat`` without a short client deadline; poll ``/processing`` while in flight."""
    cfg = resolve_poll_config(config)

    request_id = str(uuid.uuid4())
    coro = _chat_with_polling_impl(client, request, cfg, request_id)
    try:
        if cfg.max_wait_seconds and cfg.max_wait_seconds > 0:
            try:
                return await asyncio.wait_for(coro, timeout=cfg.max_wait_seconds)
            except asyncio.TimeoutError as exc:
                raise ChatServerTimeout("client max wait exceeded") from exc
        return await coro
    except ChatError as exc:
        # Tag every escaping orchestrator error with the request-id we generated, so
        # the chat reply (and operator logs) can cross-reference the same UUID.
        if exc.request_id is None:
            exc.request_id = request_id
        raise


async def _chat_with_polling_impl(
    client: OrchestratorClient,
    request: RunRequest,
    cfg: PollConfig,
    request_id: str,
) -> RunResponse:
    chat_task: asyncio.Task[RunResponse] = asyncio.create_task(client.chat(request, request_id))

    early = await _grace_wait(chat_task, cfg.grace_period)
    if early is not None:
        return early

    missed_pings = 0
    not_found_streak = 0
    immediate_ping = True

    while True:
        interval = 0.0 if immediate_ping else cfg.ping_interval
        immediate_ping = False

        sleep_task = asyncio.create_task(asyncio.sleep(interval))
        _, pending = await asyncio.wait(
            {chat_task, sleep_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        # Never cancel ``chat_task`` here: when the sleep wins the race, ``pending``
        # is ``{chat_task}`` — cancelling it would abort the in-flight POST /chat.
        for t in pending:
            if t is chat_task:
                continue
            t.cancel()
        await _await_cancelled_helper(sleep_task)

        if chat_task.done():
            return await chat_task

        try:
            status = await client.check_processing(request_id)
        except (ChatUnreachable, ChatHTTPError) as exc:
            missed_pings += 1
            if missed_pings >= cfg.max_missed_pings:
                return await _finalize_unreachable(chat_task, exc)
            continue

        missed_pings = 0

        if status.status == "processing":
            not_found_streak = 0
        elif status.status == "not_found":
            not_found_streak += 1
            if not_found_streak >= 2:
                return await _finalize_processing_lost(chat_task)
        else:
            not_found_streak = 0


async def _grace_wait(chat_task: asyncio.Task[RunResponse], grace_period: float) -> RunResponse | None:
    gp = max(0.0, grace_period)
    if gp > 0:
        sleep_task = asyncio.create_task(asyncio.sleep(gp))
        _, pending = await asyncio.wait(
            {chat_task, sleep_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            if t is chat_task:
                continue
            t.cancel()
        await _await_cancelled_helper(sleep_task)
        if chat_task.done():
            return await chat_task
        return None

    if chat_task.done():
        return await chat_task
    return None


async def _await_cancelled_helper(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _finalize_unreachable(chat_task: asyncio.Task[RunResponse], ping_exc: BaseException) -> RunResponse:
    chat_task.cancel()
    try:
        return await asyncio.wait_for(chat_task, timeout=_POST_CANCEL_DRAIN_SECONDS)
    except ChatServerTimeout:
        raise
    except ChatHTTPError:
        raise
    except ChatUnreachable:
        raise
    except (asyncio.CancelledError, asyncio.TimeoutError):
        raise ChatUnreachable(str(ping_exc)) from ping_exc


async def _finalize_processing_lost(chat_task: asyncio.Task[RunResponse]) -> RunResponse:
    chat_task.cancel()
    try:
        return await asyncio.wait_for(chat_task, timeout=_POST_CANCEL_DRAIN_SECONDS)
    except ChatServerTimeout:
        raise
    except ChatHTTPError:
        raise
    except ChatUnreachable:
        raise
    except (asyncio.CancelledError, asyncio.TimeoutError):
        raise ChatProcessingLost() from None
