"""Whoosh full-text search index (Phase 2).

Builds and queries a Whoosh inverted index over the dataset with
BM25 scoring and field boosts (title 2x, tags 1.5x). Content is
indexed but not stored; the Context Assembler loads it from disk.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from whoosh.analysis import StemmingAnalyzer
from whoosh.fields import DATETIME, ID, KEYWORD, TEXT, Schema
from whoosh.index import create_in, open_dir, exists_in
from whoosh.qparser import MultifieldParser
from whoosh.query import And, Or, Term

logger = logging.getLogger(__name__)

# Stemming so indexed terms match query_expander stemmed terms (TRD: BM25 with stemming).
_STEM = StemmingAnalyzer()

# Schema per TRD: path unique, title/tags boosted, content not stored.
SCHEMA = Schema(
    path=ID(stored=True, unique=True),
    title=TEXT(stored=True, field_boost=2.0, analyzer=_STEM),
    tags=KEYWORD(stored=True, commas=True, field_boost=1.5),
    content=TEXT(stored=False, analyzer=_STEM),
    context=ID(stored=True),
    modified=DATETIME(stored=True),
)


def get_or_create_index(index_path: Path):
    """Open an existing Whoosh index or create one with the standard schema.

    Args:
        index_path: Directory path for the index.

    Returns:
        Whoosh :class:`Index`. Creates the directory and index if missing.

    Raises:
        Exception: If the index exists but is corrupted (caller should rebuild).
    """
    index_path = Path(index_path)
    index_path.mkdir(parents=True, exist_ok=True)
    if exists_in(str(index_path)):
        return open_dir(str(index_path))
    return create_in(str(index_path), SCHEMA)


def build_from_scratch(
    dataset_reader,
    index_path: Path,
) -> None:
    """Build a Whoosh index from scratch from the dataset.

    Walks all Markdown files via the reader and indexes path, title,
    tags, content (body only), context, and modified time from disk.

    Args:
        dataset_reader: :class:`harle.dataset.reader.DatasetReader` instance.
        index_path: Directory path for the index (created/overwritten).
    """
    index_path = Path(index_path)
    if index_path.exists():
        import shutil
        shutil.rmtree(index_path)
    index_path.mkdir(parents=True, exist_ok=True)
    ix = create_in(str(index_path), SCHEMA)
    files = dataset_reader.read_all()
    writer = ix.writer()
    try:
        for f in files:
            try:
                full_path = dataset_reader.dataset_path / f.relative_path
                mtime = full_path.stat().st_mtime
                modified = datetime.fromtimestamp(mtime, tz=timezone.utc)
            except OSError:
                modified = datetime.now(timezone.utc)
            writer.add_document(
                path=f.relative_path,
                title=(f.title or "").strip(),
                tags=",".join(f.tags or []),
                content=(f.content or "").strip(),
                context=(f.context or "").strip(),
                modified=modified,
            )
        writer.commit()
    except Exception:
        writer.cancel()
        raise
    logger.info("Built Whoosh index with %d documents at %s", len(files), index_path)


def update_document(
    writer,
    *,
    path: str,
    title: str,
    tags: list[str],
    content: str,
    context: str,
    modified: datetime,
) -> None:
    """Add or update a single document in the index.

    Uses path as the unique key; existing document with same path
    is replaced. Caller must open the writer and commit after batch updates.

    Args:
        writer: Whoosh :class:`IndexWriter` from ``index.writer()``.
        path: Relative file path (unique id).
        title: Document title.
        tags: List of tags (stored as comma-separated in index).
        content: Body text (indexed, not stored).
        context: Context scope (work/personal/global).
        modified: Last modified datetime.
    """
    writer.update_document(
        path=path,
        title=title.strip(),
        tags=",".join(tags) if tags else "",
        content=content.strip(),
        context=(context or "").strip(),
        modified=modified,
    )


def remove_document(writer, path: str) -> None:
    """Remove a document from the index by path.

    Caller must commit the writer after. No-op if path not in index.

    Args:
        writer: Whoosh :class:`IndexWriter`.
        path: Relative file path to remove.
    """
    writer.delete_by_term("path", path)


def search(
    index_path: Path,
    whoosh_terms: list[str],
    candidate_paths: set[str],
    limit: int = 50,
) -> list[tuple[str, float]]:
    """Run BM25 search over the index restricted to candidate paths.

    Args:
        index_path: Directory containing the Whoosh index.
        whoosh_terms: List of terms to search for (will be joined).
        candidate_paths: Only documents with path in this set are scored.
        limit: Maximum number of results to return.

    Returns:
        List of (path, score) tuples, ordered by score descending.
    """
    index_path = Path(index_path)
    if not candidate_paths or not exists_in(str(index_path)):
        return []
    if not whoosh_terms:
        return []

    ix = open_dir(str(index_path))
    parser = MultifieldParser(["title", "tags", "content"], schema=SCHEMA)
    query_str = " ".join(whoosh_terms)
    text_query = parser.parse(query_str)

    path_filter = Or([Term("path", p) for p in candidate_paths])
    combined = And([text_query, path_filter])

    with ix.searcher() as searcher:
        results = searcher.search(combined, limit=limit)
        return [(hit["path"], float(hit.score)) for hit in results]
