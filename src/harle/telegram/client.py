"""Async HTTP client for the orchestrator (Telegram bot)."""

from __future__ import annotations

import logging

import httpx
from pydantic import ValidationError

from harle.api.models import ProcessingStatusResponse, RunRequest, RunResponse
from harle.telegram.errors import ChatHTTPError, ChatProcessingLost, ChatServerTimeout, ChatUnreachable

logger = logging.getLogger(__name__)

HARLE_CLIENT_LABEL = "telegram"
PROCESSING_PING_TIMEOUT = 10.0


class OrchestratorClient:
    """Thin wrapper around ``httpx.AsyncClient`` for ``/chat`` and ``/processing``."""

    def __init__(
        self,
        base_url: str,
        api_token: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_token = api_token.strip()
        base = base_url.rstrip("/")
        # No request timeout for POST /chat (long-running); per-call timeouts elsewhere.
        self._client = httpx.AsyncClient(
            base_url=f"{base}/",
            timeout=None,
            transport=transport,
        )

    def _headers_telegram(self) -> dict[str, str]:
        headers: dict[str, str] = {"X-Harle-Client": HARLE_CLIENT_LABEL}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"
        return headers

    def _headers_for_chat(self, request_id: str) -> dict[str, str]:
        headers = self._headers_telegram()
        headers["Content-Type"] = "application/json"
        headers["X-Request-ID"] = request_id
        return headers

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat(self, request: RunRequest, request_id: str) -> RunResponse:
        payload = request.model_dump_json(exclude_none=False)
        try:
            response = await self._client.post(
                "chat",
                content=payload,
                headers=self._headers_for_chat(request_id),
            )
        except httpx.RequestError as exc:
            raise ChatUnreachable(str(exc)) from exc

        body_text = response.text.strip()
        if response.status_code == 504:
            raise ChatServerTimeout(body_text or "gateway timeout")
        if response.status_code >= 400:
            raise ChatHTTPError(response.status_code, body_text)

        try:
            return RunResponse.model_validate_json(response.text)
        except ValidationError as exc:
            logger.exception("Invalid JSON from POST /chat")
            raise ChatHTTPError(response.status_code, response.text) from exc

    async def check_processing(self, request_id: str) -> ProcessingStatusResponse:
        try:
            response = await self._client.get(
                f"processing/{request_id}",
                headers=self._headers_telegram(),
                timeout=PROCESSING_PING_TIMEOUT,
            )
        except httpx.RequestError as exc:
            raise ChatUnreachable(str(exc)) from exc

        if response.status_code >= 400:
            raise ChatHTTPError(response.status_code, response.text.strip())
        try:
            return ProcessingStatusResponse.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise ChatHTTPError(response.status_code, response.text) from exc


__all__ = ["HARLE_CLIENT_LABEL", "OrchestratorClient", "PROCESSING_PING_TIMEOUT"]
