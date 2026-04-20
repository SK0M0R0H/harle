"""Tests for OrchestratorClient."""

from __future__ import annotations

import json

import httpx
import pytest

from harle.api.models import RunRequest, RunResponse
from harle.telegram.client import HARLE_CLIENT_LABEL, OrchestratorClient
from harle.telegram.errors import ChatHTTPError, ChatServerTimeout, ChatUnreachable


@pytest.mark.asyncio
async def test_chat_headers_and_body() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "run_id": "r1",
                "status": "completed",
                "result": "hi",
                "context": "personal",
            },
        )

    transport = httpx.MockTransport(handler)
    client = OrchestratorClient("http://orch.example", "secret", transport=transport)
    try:
        rid = "req-test-1"
        resp = await client.chat(
            RunRequest(message="hello", context="personal", conversation_id=None),
            rid,
        )
    finally:
        await client.aclose()

    assert isinstance(resp, RunResponse)
    assert resp.result == "hi"
    headers = captured["headers"]  # type: ignore[assignment]
    assert headers["x-harle-client"] == HARLE_CLIENT_LABEL  # httpx lowercases keys
    assert headers["x-request-id"] == rid
    assert headers["authorization"] == "Bearer secret"
    body = captured["body"]  # type: ignore[assignment]
    assert body["message"] == "hello"
    assert body["context"] == "personal"
    assert body["conversation_id"] is None


@pytest.mark.asyncio
async def test_chat_no_bearer_when_token_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in {k.lower() for k in request.headers}
        return httpx.Response(
            200,
            json={
                "run_id": "r1",
                "status": "completed",
                "result": "ok",
                "context": "personal",
            },
        )

    transport = httpx.MockTransport(handler)
    client = OrchestratorClient("http://orch.example", "", transport=transport)
    try:
        await client.chat(RunRequest(message="x", context="personal"), "id")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_chat_504() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(504, text="timeout"))
    client = OrchestratorClient("http://orch.example", "", transport=transport)
    try:
        with pytest.raises(ChatServerTimeout):
            await client.chat(RunRequest(message="x", context="personal"), "id")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_chat_request_error() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope", request=request)

    transport = httpx.MockTransport(boom)
    client = OrchestratorClient("http://orch.invalid", "", transport=transport)
    try:
        with pytest.raises(ChatUnreachable):
            await client.chat(RunRequest(message="x", context="personal"), "id")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_check_processing_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/processing/abc" in str(request.url)
        assert request.headers.get("x-harle-client") == HARLE_CLIENT_LABEL
        return httpx.Response(200, json={"request_id": "abc", "status": "processing", "started_at": None})

    transport = httpx.MockTransport(handler)
    client = OrchestratorClient("http://orch.example", "tok", transport=transport)
    try:
        st = await client.check_processing("abc")
        assert st.status == "processing"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_chat_http_error() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(409, text="conflict"))
    client = OrchestratorClient("http://orch.example", "", transport=transport)
    try:
        with pytest.raises(ChatHTTPError) as ei:
            await client.chat(RunRequest(message="x", context="personal"), "id")
        assert ei.value.status_code == 409
    finally:
        await client.aclose()
