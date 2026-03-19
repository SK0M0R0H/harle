"""Whoosh full-text search index (Phase 2).

Builds and queries a Whoosh inverted index over the dataset with
BM25 scoring and field boosts (title 2x, tags 1.5x). Long files may
be split into multiple documents (chunks) with composite ``path`` ids;
``file_path`` links chunks to the vault file for filtering and deletion.
"""

from __future__ import annotations

import logging
import shutil
from types import SimpleNamespace
from typing import Any
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from whoosh.analysis import StemmingAnalyzer
from whoosh.fields import DATETIME, ID, KEYWORD, STORED, TEXT, Schema
from whoosh.index import create_in, open_dir, exists_in as _whoosh_exists_in
from whoosh.qparser import MultifieldParser
from whoosh.query import And, Or, Term

from harle.context.tokenizer import count_tokens
from harle.indexing.chunker import (
    chunk_file,
    get_strategy,
    parse_whoosh_doc_path,
    whoosh_doc_path,
)

logger = logging.getLogger(__name__)


def exists_in(index_path: str) -> bool:
    """Return True if *index_path* contains a valid Whoosh index."""
    return _whoosh_exists_in(str(index_path))

# Stemming so indexed terms match query_expander stemmed terms (TRD: BM25 with stemming).
_STEM = StemmingAnalyzer()

# path = unique doc id (plain file path or file_path#chunk_index).
SCHEMA = Schema(
    path=ID(stored=True, unique=True),
    file_path=ID(stored=True),
    chunk_index=ID(stored=True),
    heading_path=STORED,
    title=TEXT(stored=True, field_boost=2.0, analyzer=_STEM),
    tags=KEYWORD(stored=True, commas=True, field_boost=1.5),
    content=TEXT(stored=False, analyzer=_STEM),
    context=ID(stored=True),
    modified=DATETIME(stored=True),
)


@dataclass(frozen=True)
class WhooshSearchHit:
    """One BM25 hit with chunk metadata."""

    doc_path: str
    score: float
    file_path: str
    chunk_index: int | None
    heading_path: str


def _default_chunking():
    from harle.config import get_chunking_config

    return get_chunking_config()


def write_file_to_index(
    writer,
    f,
    modified: datetime,
    chunking,
    *,
    delete_existing: bool,
) -> int:
    """Index one dataset file as one or more Whoosh documents.

    Args:
        writer: Whoosh :class:`IndexWriter`.
        f: :class:`harle.dataset.reader.DatasetFile`-like (relative_path, title, tags, content, context).
        modified: Last-modified time for the document(s).
        chunking: :class:`harle.config.ChunkingConfig`.
        delete_existing: If True, remove existing docs with the same ``file_path`` first.

    Returns:
        Number of Whoosh documents written.
    """
    rel = f.relative_path
    if delete_existing:
        remove_documents_by_file_path(writer, rel)

    body = (f.content or "").strip()
    token_count = count_tokens(body)
    strategy = get_strategy(
        rel,
        token_count,
        chunking_enabled=chunking.enabled,
        knowledge_token_threshold=chunking.knowledge_token_threshold,
    )
    chunks = chunk_file(
        content=f.content or "",
        title=f.title,
        tags=list(f.tags or []),
        context=f.context,
        relative_path=rel,
        strategy=strategy,
        contextual_enrichment=chunking.contextual_enrichment,
        paragraph_max_tokens=chunking.paragraph_max_tokens,
    )
    num = len(chunks)
    title_s = (f.title or "").strip()
    ctx = (f.context or "").strip()
    tags_csv = ",".join(f.tags or [])

    for c in chunks:
        doc_path = whoosh_doc_path(c.file_path, c.chunk_index, num)
        indexed_body = (c.context_block + c.content).strip()
        writer.add_document(
            path=doc_path,
            file_path=c.file_path,
            chunk_index=str(c.chunk_index),
            heading_path=c.heading_path,
            title=title_s,
            tags=tags_csv,
            content=indexed_body,
            context=ctx,
            modified=modified,
        )
    return num


def _whoosh_schema_matches(ix) -> bool:
    """True if an opened index has the same field names as :data:`SCHEMA`."""
    try:
        existing = frozenset(ix.schema.names())
    except Exception:  # noqa: BLE001
        return False
    return existing == frozenset(SCHEMA.names())


def disk_index_schema_current(index_path: Path) -> bool:
    """True if there is no Whoosh index at *index_path* or it matches :data:`SCHEMA`.

    Used by :class:`harle.indexing.indexer.Indexer` to trigger a full
    :func:`build_from_scratch` before incremental updates, so schema upgrades
    do not leave a partial index.
    """
    p = Path(index_path)
    if not _whoosh_exists_in(str(p)):
        return True
    try:
        ix = open_dir(str(p))
    except Exception:  # noqa: BLE001
        return False
    try:
        return _whoosh_schema_matches(ix)
    finally:
        ix.close()


def get_or_create_index(index_path: Path) -> tuple[Any, bool]:
    """Open an existing Whoosh index or create one with the standard schema.

    If an older index directory exists with a different schema (e.g. missing
    ``chunk_index`` / ``file_path``), the directory is removed and a fresh
    empty index is created so incremental updates do not fail at runtime.

    Returns:
        ``(index, schema_was_reset)``. When ``schema_was_reset`` is True,
        :func:`harle.indexing.indexer._sync_whoosh` runs :func:`build_from_scratch`
        so the index is fully repopulated (incremental sync only passes
        changed files).

    Indexer also checks :func:`disk_index_schema_current` before incremental
    work so a stale schema triggers a full rebuild even when no files changed.
    """
    index_path = Path(index_path)
    index_path.mkdir(parents=True, exist_ok=True)
    if _whoosh_exists_in(str(index_path)):
        ix = open_dir(str(index_path))
        if not _whoosh_schema_matches(ix):
            logger.info(
                "Whoosh schema at %s is outdated; recreating index (full re-index follows).",
                index_path,
            )
            ix.close()
            shutil.rmtree(index_path)
            index_path.mkdir(parents=True, exist_ok=True)
            return create_in(str(index_path), SCHEMA), True
        return ix, False
    return create_in(str(index_path), SCHEMA), False


def build_from_scratch(
    dataset_reader,
    index_path: Path,
    chunking=None,
) -> None:
    """Build a Whoosh index from scratch from the dataset.

    Args:
        dataset_reader: :class:`harle.dataset.reader.DatasetReader` instance.
        index_path: Directory path for the index (created/overwritten).
        chunking: Optional :class:`ChunkingConfig`; defaults from config file.
    """
    index_path = Path(index_path)
    if index_path.exists():
        import shutil

        shutil.rmtree(index_path)
    index_path.mkdir(parents=True, exist_ok=True)
    if chunking is None:
        chunking = _default_chunking()
    ix = create_in(str(index_path), SCHEMA)
    files = dataset_reader.read_all()
    writer = ix.writer()
    doc_count = 0
    try:
        for f in files:
            try:
                full_path = dataset_reader.dataset_path / f.relative_path
                mtime = full_path.stat().st_mtime
                modified = datetime.fromtimestamp(mtime, tz=timezone.utc)
            except OSError:
                modified = datetime.now(timezone.utc)
            n = write_file_to_index(
                writer, f, modified, chunking, delete_existing=False
            )
            doc_count += n
        writer.commit()
    except Exception:
        writer.cancel()
        raise
    logger.info(
        "Built Whoosh index with %d document(s) from %d file(s) at %s",
        doc_count,
        len(files),
        index_path,
    )


def update_document(
    writer,
    *,
    path: str,
    title: str,
    tags: list[str],
    content: str,
    context: str,
    modified: datetime,
    chunking=None,
    file_obj=None,
) -> None:
    """Replace all index entries for a single vault file (legacy API shape).

    Prefer :func:`write_file_to_index` when you have a :class:`DatasetFile`.

    Args:
        writer: Whoosh :class:`IndexWriter`.
        path: Vault-relative file path (same as DatasetFile.relative_path).
        title, tags, content, context: Same as dataset file fields.
        modified: Last modified time.
        chunking: Optional :class:`ChunkingConfig`.
        file_obj: Optional DatasetFile; if provided, ``path``/fields may be taken from it.
    """
    if chunking is None:
        chunking = _default_chunking()
    if file_obj is not None:
        write_file_to_index(writer, file_obj, modified, chunking, delete_existing=True)
        return

    pseudo_file = SimpleNamespace(
        relative_path=path,
        title=title,
        tags=tags,
        content=content,
        context=context,
    )
    write_file_to_index(writer, pseudo_file, modified, chunking, delete_existing=True)


def remove_document(writer, path: str) -> None:
    """Remove a document by its Whoosh ``path`` (unique id)."""
    writer.delete_by_term("path", path)


def remove_documents_by_file_path(writer, file_path: str) -> None:
    """Remove all chunk documents belonging to a vault file."""
    writer.delete_by_term("file_path", file_path)


def search(
    index_path: Path,
    whoosh_terms: list[str],
    candidate_paths: set[str],
    limit: int = 50,
) -> list[WhooshSearchHit]:
    """Run BM25 search restricted to candidate vault file paths."""
    index_path = Path(index_path)
    if not candidate_paths or not _whoosh_exists_in(str(index_path)):
        return []
    if not whoosh_terms:
        return []

    ix = open_dir(str(index_path))
    parser = MultifieldParser(["title", "tags", "content"], schema=SCHEMA)
    query_str = " ".join(whoosh_terms)
    text_query = parser.parse(query_str)

    path_filter = Or([Term("file_path", p) for p in candidate_paths])
    combined = And([text_query, path_filter])

    with ix.searcher() as searcher:
        results = searcher.search(combined, limit=limit)
        hits: list[WhooshSearchHit] = []
        for hit in results:
            doc_path = hit["path"]
            fp = hit.get("file_path") or parse_whoosh_doc_path(doc_path)[0]
            if "#" in doc_path:
                _, parsed_ci = parse_whoosh_doc_path(doc_path)
                chunk_idx: int | None = (
                    parsed_ci
                    if parsed_ci is not None
                    else int(hit.get("chunk_index") or 0)
                )
            else:
                chunk_idx = None
            hp_raw = hit.get("heading_path")
            hp = (hp_raw or "").strip() if isinstance(hp_raw, str) else ""
            hits.append(
                WhooshSearchHit(
                    doc_path=doc_path,
                    score=float(hit.score),
                    file_path=fp,
                    chunk_index=chunk_idx,
                    heading_path=hp,
                )
            )
        return hits
