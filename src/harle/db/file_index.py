"""CRUD operations for the ``file_index`` table.

Provides query helpers used by the search engine and the indexer.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from harle.db.models import FileIndex


def get_all_tags(session: Session) -> set[str]:
    """Return the set of all distinct tags in the file index.

    Used by the query expander to match query terms against the tag
    vocabulary. Safe for small-to-medium datasets (hundreds of files).

    Returns:
        Set of tag strings (lowercased for consistent matching).
    """
    rows = session.scalars(select(FileIndex)).all()
    tags: set[str] = set()
    for row in rows:
        if row.tags:
            for t in row.tags:
                if t:
                    tags.add(t.lower())
    return tags


def get_candidates_for_search(
    session: Session,
    *,
    context: str | None,
    tag_filters: list[str] | None = None,
    include_global: bool = True,
) -> list[FileIndex]:
    """Return file index entries that are candidates for search (Phase 2).

    Applies context scope (including global/null when include_global),
    optional tag overlap, and always includes P0 paths (prompts/, policies/).

    Args:
        session: Active SQLAlchemy session.
        context: Context scope (e.g. ``"work"`` or ``"personal"``).
            If None, no context filter is applied.
        tag_filters: If non-empty, only entries whose tags overlap
            this list are included (plus P0).
        include_global: If True, include entries with context
            ``"global"`` or NULL when filtering by context.

    Returns:
        List of :class:`FileIndex` rows, ordered by last_modified DESC.
    """
    stmt = select(FileIndex).order_by(FileIndex.last_modified.desc())

    if context is not None:
        scope_cond = or_(
            FileIndex.context == context,
            FileIndex.context == "global",
            FileIndex.context.is_(None),
        )
        if not include_global:
            scope_cond = FileIndex.context == context
    else:
        scope_cond = True

    p0_cond = or_(
        FileIndex.file_path.startswith("prompts/"),
        FileIndex.file_path.startswith("policies/"),
    )

    if tag_filters:
        tag_cond = FileIndex.tags.overlap(tag_filters)
        stmt = stmt.where(or_(p0_cond, (scope_cond & tag_cond)))
    else:
        stmt = stmt.where(or_(p0_cond, scope_cond))

    return list(session.scalars(stmt).all())


def get_entries_by_paths(
    session: Session,
    paths: list[str],
) -> list[FileIndex]:
    """Return file index entries for the given relative paths.

    Used to enrich Whoosh results with token_count, summary, last_modified.
    Entries not found are omitted; order is not guaranteed.

    Args:
        session: Active SQLAlchemy session.
        paths: Relative paths within the dataset.

    Returns:
        List of :class:`FileIndex` rows for paths that exist.
    """
    if not paths:
        return []
    stmt = select(FileIndex).where(FileIndex.file_path.in_(paths))
    return list(session.scalars(stmt).all())


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
