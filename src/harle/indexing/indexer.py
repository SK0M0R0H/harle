"""Dataset-to-database sync pipeline.

Scans the user dataset, compares file hashes with the ``file_index``
table, and inserts or updates rows for new or changed files.  Removes
rows for files that no longer exist on disk.  Optionally updates the
Whoosh full-text index for Phase 2 search.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from harle.dataset.reader import DatasetReader
from harle.db.connection import Database
from harle.db.models import FileIndex
from harle.context.tokenizer import count_tokens
from harle.indexing.hasher import compute_hash

logger = logging.getLogger(__name__)


class Indexer:
    """Synchronises the dataset directory with the ``file_index`` table.

    Args:
        db: Database instance for reading/writing file_index.
        reader: Dataset reader for listing and parsing vault files.
        whoosh_index_path: Optional path to the Whoosh index directory.
            When set, sync will update/remove documents for changed/deleted files.
    """

    def __init__(
        self,
        db: Database,
        reader: DatasetReader,
        whoosh_index_path: str | Path | None = None,
        chunking=None,
    ) -> None:
        self.db = db
        self.reader = reader
        self.whoosh_index_path = Path(whoosh_index_path).expanduser() if whoosh_index_path else None
        self._chunking = chunking

    def sync(self) -> int:
        """Perform a full incremental sync.

        Walks the dataset, compares content hashes, and updates the
        database.  Only changed or new files are processed.  If
        whoosh_index_path is set, updates the Whoosh index for
        added/updated/deleted files.

        Returns:
            Number of file_index rows added, updated, or deleted.
        """
        files = self.reader.read_all()
        changes = 0
        now = datetime.now(timezone.utc)
        whoosh_updated: list = []  # DatasetFile for add/update
        whoosh_deleted: list[str] = []

        whoosh_schema_stale = False
        if self.whoosh_index_path:
            from harle.search import whoosh_index

            p = self.whoosh_index_path
            if p.exists() and whoosh_index.exists_in(str(p)):
                whoosh_schema_stale = not whoosh_index.disk_index_schema_current(p)

        with self.db.session() as session:
            existing: dict[str, FileIndex] = {
                row.file_path: row
                for row in session.scalars(select(FileIndex)).all()
            }
            seen_paths: set[str] = set()

            for f in files:
                seen_paths.add(f.relative_path)
                content_hash = compute_hash(f.raw_content)

                if f.relative_path in existing:
                    row = existing[f.relative_path]
                    if row.content_hash == content_hash:
                        continue
                    # File changed — update the row.
                    row.title = f.title
                    row.tags = f.tags if f.tags else None
                    row.context = f.context
                    row.content_hash = content_hash
                    row.char_count = len(f.raw_content)
                    row.token_count = count_tokens(f.raw_content or "")
                    row.last_modified = now
                    row.last_indexed = now
                    logger.info("Updated index for %s", f.relative_path)
                    whoosh_updated.append(f)
                else:
                    # New file — insert.
                    session.add(
                        FileIndex(
                            file_path=f.relative_path,
                            title=f.title,
                            tags=f.tags if f.tags else None,
                            context=f.context,
                            content_hash=content_hash,
                            char_count=len(f.raw_content),
                            token_count=count_tokens(f.raw_content or ""),
                            last_modified=now,
                            last_indexed=now,
                        )
                    )
                    logger.info("Indexed new file %s", f.relative_path)
                    whoosh_updated.append(f)
                changes += 1

            # Remove rows for files that no longer exist.
            for path in set(existing.keys()) - seen_paths:
                session.delete(existing[path])
                logger.info("Removed index entry for deleted file %s", path)
                whoosh_deleted.append(path)
                changes += 1

        if self.whoosh_index_path:
            from harle.config import get_chunking_config

            chunking = self._chunking if self._chunking is not None else get_chunking_config()
            if whoosh_schema_stale:
                from harle.search import whoosh_index

                whoosh_index.build_from_scratch(
                    self.reader, self.whoosh_index_path, chunking
                )
            elif whoosh_updated or whoosh_deleted:
                _sync_whoosh(
                    self.whoosh_index_path,
                    self.reader,
                    whoosh_updated,
                    whoosh_deleted,
                    now,
                    chunking,
                )

        logger.info(
            "Sync complete: %d change(s), %d file(s) in dataset.",
            changes,
            len(files),
        )
        return changes


def _sync_whoosh(
    index_path: Path,
    reader: DatasetReader,
    updated: list,
    deleted: list[str],
    modified: datetime,
    chunking,
) -> None:
    """Update the Whoosh index for the given added/updated and deleted paths."""
    from harle.search import whoosh_index

    if not index_path.exists():
        logger.debug("Whoosh index path does not exist; skip incremental update.")
        return

    if not whoosh_index.exists_in(str(index_path)):
        logger.debug("Whoosh index not present at %s; skip incremental update.", index_path)
        return

    try:
        ix, schema_reset = whoosh_index.get_or_create_index(index_path)
        if schema_reset:
            ix.close()
            whoosh_index.build_from_scratch(reader, index_path, chunking)
            return
        writer = ix.writer()
        for f in updated:
            whoosh_index.update_document(
                writer,
                path=f.relative_path,
                title=(f.title or "").strip(),
                tags=f.tags or [],
                content=(f.content or "").strip(),
                context=(f.context or "").strip(),
                modified=modified,
                chunking=chunking,
                file_obj=f,
            )
        for path in deleted:
            whoosh_index.remove_documents_by_file_path(writer, path)
        writer.commit()
        logger.info(
            "Whoosh index updated: %d file(s) re-indexed, %d file(s) removed.",
            len(updated),
            len(deleted),
        )
    except Exception as e:
        logger.warning("Whoosh index update failed: %s", e)
