"""Tests for chat_with_polling."""

from __future__ import annotations

import asyncio

import pytest

from harle.api.models import ProcessingStatusResponse, RunRequest, RunResponse
from harle.telegram.errors import ChatProcessingLost, ChatServerTimeout, ChatUnreachable
from harle.telegram.processing import PollConfig, chat_with_polling


class _FakeOrchestrator:
    """Minimal duck-typed client for :func:`chat_with_polling`."""

    def __init__(self) -> None:
        self.check_calls = 0

    async def chat(self, request: RunRequest, request_id: str) -> RunResponse:
        raise NotImplementedError

    async def check_processing(self, request_id: str) -> ProcessingStatusResponse:
        raise NotImplementedError


@pytest.mark.asyncio
async def test_returns_when_chat_finishes_before_pings() -> None:
    class C(_FakeOrchestrator):
        async def chat(self, request: RunRequest, request_id: str) -> RunResponse:
            return RunResponse(
                run_id="1",
                status="completed",
                result="done",
                context="personal",
            )

        async def check_processing(self, request_id: str) -> ProcessingStatusResponse:
            self.check_calls += 1
            return ProcessingStatusResponse(
                request_id=request_id,
                status="processing",
                started_at="2020-01-01T00:00:00+00:00",
            )

    c = C()
    cfg = PollConfig(ping_interval=0.05, max_missed_pings=3, grace_period=0.0)
    out = await chat_with_polling(
        c,  # type: ignore[arg-type]
        RunRequest(message="hi", context="personal"),
        config=cfg,
    )
    assert out.result == "done"


@pytest.mark.asyncio
async def test_unreachable_after_missed_pings() -> None:
    class C(_FakeOrchestrator):
        async def chat(self, request: RunRequest, request_id: str) -> RunResponse:
            await asyncio.sleep(10.0)
            return RunResponse(
                run_id="1",
                status="completed",
                result="never",
                context="personal",
            )

        async def check_processing(self, request_id: str) -> ProcessingStatusResponse:
            self.check_calls += 1
            raise ChatUnreachable("down")

    c = C()
    cfg = PollConfig(ping_interval=0.01, max_missed_pings=2, grace_period=0.0)
    with pytest.raises(ChatUnreachable):
        await chat_with_polling(
            c,  # type: ignore[arg-type]
            RunRequest(message="hi", context="personal"),
            config=cfg,
        )
    assert c.check_calls >= 2


@pytest.mark.asyncio
async def test_processing_lost_two_not_found() -> None:
    class C(_FakeOrchestrator):
        async def chat(self, request: RunRequest, request_id: str) -> RunResponse:
            await asyncio.sleep(10.0)
            return RunResponse(
                run_id="1",
                status="completed",
                result="never",
                context="personal",
            )

        async def check_processing(self, request_id: str) -> ProcessingStatusResponse:
            self.check_calls += 1
            if self.check_calls <= 1:
                return ProcessingStatusResponse(
                    request_id=request_id,
                    status="processing",
                    started_at="2020-01-01T00:00:00+00:00",
                )
            return ProcessingStatusResponse(request_id=request_id, status="not_found", started_at=None)

    c = C()
    cfg = PollConfig(ping_interval=0.01, max_missed_pings=5, grace_period=0.0)
    with pytest.raises(ChatProcessingLost):
        await chat_with_polling(
            c,  # type: ignore[arg-type]
            RunRequest(message="hi", context="personal"),
            config=cfg,
        )


@pytest.mark.asyncio
async def test_request_id_attached_to_unreachable() -> None:
    seen: list[str] = []

    class C(_FakeOrchestrator):
        async def chat(self, request: RunRequest, request_id: str) -> RunResponse:
            seen.append(request_id)
            await asyncio.sleep(10.0)
            return RunResponse(run_id="1", status="completed", result="x", context="personal")

        async def check_processing(self, request_id: str) -> ProcessingStatusResponse:
            raise ChatUnreachable("down")

    c = C()
    cfg = PollConfig(ping_interval=0.01, max_missed_pings=2, grace_period=0.0)
    with pytest.raises(ChatUnreachable) as ei:
        await chat_with_polling(c, RunRequest(message="hi", context="personal"), config=cfg)  # type: ignore[arg-type]

    assert ei.value.request_id is not None
    assert ei.value.request_id == seen[0], "exception must carry the same UUID the bot sent on POST /chat"


@pytest.mark.asyncio
async def test_request_id_attached_to_processing_lost() -> None:
    seen: list[str] = []

    class C(_FakeOrchestrator):
        async def chat(self, request: RunRequest, request_id: str) -> RunResponse:
            seen.append(request_id)
            await asyncio.sleep(10.0)
            return RunResponse(run_id="1", status="completed", result="x", context="personal")

        async def check_processing(self, request_id: str) -> ProcessingStatusResponse:
            return ProcessingStatusResponse(request_id=request_id, status="not_found", started_at=None)

    c = C()
    cfg = PollConfig(ping_interval=0.01, max_missed_pings=5, grace_period=0.0)
    with pytest.raises(ChatProcessingLost) as ei:
        await chat_with_polling(c, RunRequest(message="hi", context="personal"), config=cfg)  # type: ignore[arg-type]
    assert ei.value.request_id == seen[0]


@pytest.mark.asyncio
async def test_max_wait_seconds() -> None:
    class C(_FakeOrchestrator):
        async def chat(self, request: RunRequest, request_id: str) -> RunResponse:
            await asyncio.sleep(1.0)
            return RunResponse(
                run_id="1",
                status="completed",
                result="late",
                context="personal",
            )

        async def check_processing(self, request_id: str) -> ProcessingStatusResponse:
            return ProcessingStatusResponse(
                request_id=request_id,
                status="processing",
                started_at="2020-01-01T00:00:00+00:00",
            )

    c = C()
    cfg = PollConfig(ping_interval=0.05, max_missed_pings=10, grace_period=0.0, max_wait_seconds=0.08)
    with pytest.raises(ChatServerTimeout) as ei:
        await chat_with_polling(
            c,  # type: ignore[arg-type]
            RunRequest(message="hi", context="personal"),
            config=cfg,
        )
    assert ei.value.request_id is not None and len(ei.value.request_id) >= 32
