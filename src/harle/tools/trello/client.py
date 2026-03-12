"""Trello client wrapper with normalized response shapes and errors."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx


class TrelloClientError(RuntimeError):
    """Raised when Trello API calls fail in a normalized way."""


@dataclass(frozen=True)
class TrelloBoard:
    """Stable internal board shape."""

    id: str
    name: str
    url: str
    closed: bool


@dataclass(frozen=True)
class TrelloCard:
    """Stable internal card shape."""

    id: str
    name: str
    url: str
    closed: bool
    id_list: str
    due: str | None = None


@dataclass
class TrelloClient:
    """Read-focused Trello API client using a connection-managed HTTP client."""

    http_client: httpx.AsyncClient | None = None
    _http: httpx.AsyncClient = field(default=None, init=False, repr=False)  # type: ignore[assignment]

    async def open(self) -> None:
        if self.http_client is None:
            raise RuntimeError("TrelloClient requires a connection-managed HTTP client.")
        self._http = self.http_client

    async def close(self) -> None:
        """Release local client reference; connection owns lifecycle."""
        self._http = None  # type: ignore[assignment]

    async def list_boards(self) -> list[TrelloBoard]:
        """Return boards available to the current authenticated member."""
        self._ensure_open()
        data = await self._get_json("/members/me/boards", params={"fields": "id,name,url,closed"})
        return [
            TrelloBoard(
                id=item.get("id", ""),
                name=item.get("name", ""),
                url=item.get("url", ""),
                closed=bool(item.get("closed", False)),
            )
            for item in data
            if isinstance(item, dict)
        ]

    async def list_cards(self, board_id: str) -> list[TrelloCard]:
        """Return cards for a board in stable internal format."""
        self._ensure_open()
        data = await self._get_json(
            f"/boards/{board_id}/cards",
            params={"fields": "id,name,url,closed,idList,due"},
        )
        return [
            TrelloCard(
                id=item.get("id", ""),
                name=item.get("name", ""),
                url=item.get("url", ""),
                closed=bool(item.get("closed", False)),
                id_list=item.get("idList", ""),
                due=item.get("due"),
            )
            for item in data
            if isinstance(item, dict)
        ]

    async def _get_json(self, path: str, *, params: dict[str, object] | None = None) -> list[dict]:
        try:
            response = await self._http.get(path, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            raise TrelloClientError(f"Trello API error (status={status}): {exc}") from exc
        except Exception as exc:
            raise TrelloClientError(f"Trello request failed: {exc}") from exc

        if not isinstance(payload, list):
            raise TrelloClientError("Unexpected Trello response format: expected a list.")
        return payload

    def _ensure_open(self) -> None:
        if self._http is None:
            raise RuntimeError(
                "TrelloClient is not open. Call `await client.open()` first, "
                "or use TrelloModule.initialize()."
            )


_active_client: TrelloClient | None = None


def set_client(client: TrelloClient) -> None:
    global _active_client
    _active_client = client


def get_client() -> TrelloClient:
    if _active_client is None:
        raise RuntimeError(
            "Trello client is not initialised. Ensure TrelloModule.initialize() has been called."
        )
    return _active_client


def clear_client() -> None:
    global _active_client
    _active_client = None
