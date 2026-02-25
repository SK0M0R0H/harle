"""Dummy tool functions for testing the registry and SDK integration."""

from __future__ import annotations


async def dummy_read(item_id: str) -> str:
    """Read a dummy item by its identifier.

    Args:
        item_id: The unique identifier of the item to read.

    Returns:
        A JSON string with the item data.
    """
    return f'{{"id": "{item_id}", "status": "found"}}'


dummy_read.permission = "read"  # type: ignore[attr-defined]
dummy_read.requires_approval = False  # type: ignore[attr-defined]


async def dummy_create(title: str, category: str = "general") -> str:
    """Create a new dummy item.

    Args:
        title: Title for the new item.
        category: Category to file the item under.

    Returns:
        A JSON string with the created item's id and title.
    """
    return f'{{"id": "new_001", "title": "{title}", "category": "{category}"}}'


dummy_create.permission = "write"  # type: ignore[attr-defined]
dummy_create.requires_approval = True  # type: ignore[attr-defined]


async def dummy_delete(item_id: str) -> str:
    """Delete a dummy item.

    Args:
        item_id: The unique identifier of the item to delete.

    Returns:
        Confirmation message.
    """
    return f"Item {item_id} deleted."


dummy_delete.permission = "delete"  # type: ignore[attr-defined]
dummy_delete.requires_approval = True  # type: ignore[attr-defined]
