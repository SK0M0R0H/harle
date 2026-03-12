"""Read-only tool functions for the Trello tool module."""

from __future__ import annotations

import json

from harle.tools.trello.client import TrelloClientError, get_client


async def trello_list_boards() -> str:
    """List Trello boards visible to the configured member credentials.

    Returns:
        JSON with a ``boards`` array. Each board includes ``id``, ``name``,
        ``url``, and ``closed``.
    """
    try:
        client = get_client()
        boards = await client.list_boards()
        return json.dumps({
            "boards": [
                {
                    "id": b.id,
                    "name": b.name,
                    "url": b.url,
                    "closed": b.closed,
                }
                for b in boards
            ],
        }, ensure_ascii=False)
    except (TrelloClientError, RuntimeError) as exc:
        return json.dumps({
            "boards": [],
            "error": True,
            "message": f"Trello connection error: {exc}",
        }, ensure_ascii=False)


trello_list_boards.permission = "read"  # type: ignore[attr-defined]
trello_list_boards.requires_approval = False  # type: ignore[attr-defined]


async def trello_list_cards(board_id: str) -> str:
    """List cards for a Trello board.

    Args:
        board_id: Trello board ID.

    Returns:
        JSON with ``board_id`` and ``cards`` array. Each card includes
        ``id``, ``name``, ``url``, ``closed``, ``id_list``, and ``due``.
    """
    if not board_id.strip():
        return json.dumps({
            "board_id": board_id,
            "cards": [],
            "error": True,
            "message": "board_id is required.",
        }, ensure_ascii=False)

    try:
        client = get_client()
        cards = await client.list_cards(board_id.strip())
        return json.dumps({
            "board_id": board_id.strip(),
            "cards": [
                {
                    "id": c.id,
                    "name": c.name,
                    "url": c.url,
                    "closed": c.closed,
                    "id_list": c.id_list,
                    "due": c.due,
                }
                for c in cards
            ],
        }, ensure_ascii=False)
    except (TrelloClientError, RuntimeError) as exc:
        return json.dumps({
            "board_id": board_id.strip(),
            "cards": [],
            "error": True,
            "message": f"Trello connection error: {exc}",
        }, ensure_ascii=False)


trello_list_cards.permission = "read"  # type: ignore[attr-defined]
trello_list_cards.requires_approval = False  # type: ignore[attr-defined]
