"""CRUD operations for the ``file_index`` table.

Provides query helpers used by the search engine and the indexer.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from harle.db.models import FileIndex


def get_all_entries(
    session: Session,
    *,
    context: str | None = None,
) -> list[FileIndex]:
    """Return all file index entries, optionally filtered by context.

    Args:
        session: Active SQLAlchemy session.
        context: If provided, only return entries matching this context
            scope (e.g. ``"work"`` or ``"personal"``).

    Returns:
        List of :class:`FileIndex` rows.
    """
    stmt = select(FileIndex)
    if context:
        stmt = stmt.where(FileIndex.context == context)
    return list(session.scalars(stmt).all())


def get_entry_by_path(session: Session, file_path: str) -> FileIndex | None:
    """Look up a single file index entry by its relative path.

    Args:
        session: Active SQLAlchemy session.
        file_path: Relative path within the dataset (e.g.
            ``"policies/privacy.md"``).

    Returns:
        The matching :class:`FileIndex` row, or ``None``.
    """
    stmt = select(FileIndex).where(FileIndex.file_path == file_path)
    return session.scalars(stmt).first()


def delete_missing_entries(
    session: Session,
    existing_paths: set[str],
) -> int:
    """Remove file_index rows whose files no longer exist on disk.

    Args:
        session: Active SQLAlchemy session.
        existing_paths: Set of relative paths that currently exist in
            the dataset directory.

    Returns:
        Number of rows deleted.
    """
    all_entries = list(session.scalars(select(FileIndex)).all())
    deleted = 0
    for entry in all_entries:
        if entry.file_path not in existing_paths:
            session.delete(entry)
            deleted += 1
    return deleted
