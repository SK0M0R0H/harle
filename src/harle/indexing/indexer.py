"""Dataset-to-database sync pipeline.

Scans the user dataset, compares file hashes with the ``file_index``
table, and inserts or updates rows for new or changed files.  Removes
rows for files that no longer exist on disk.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from harle.dataset.reader import DatasetReader
from harle.db.connection import Database
from harle.db.models import FileIndex
from harle.indexing.hasher import compute_hash

logger = logging.getLogger(__name__)


class Indexer:
    """Synchronises the dataset directory with the ``file_index`` table.

    Args:
        db: Database instance for reading/writing file_index.
        reader: Dataset reader for listing and parsing vault files.
    """

    def __init__(self, db: Database, reader: DatasetReader) -> None:
        self.db = db
        self.reader = reader

    def sync(self) -> int:
        """Perform a full incremental sync.

        Walks the dataset, compares content hashes, and updates the
        database.  Only changed or new files are processed.

        Returns:
            Number of file_index rows added, updated, or deleted.
        """
        files = self.reader.read_all()
        changes = 0
        now = datetime.now(timezone.utc)

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
                    row.token_count = len(f.raw_content) // 4
                    row.last_modified = now
                    row.last_indexed = now
                    logger.info("Updated index for %s", f.relative_path)
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
                            token_count=len(f.raw_content) // 4,
                            last_modified=now,
                            last_indexed=now,
                        )
                    )
                    logger.info("Indexed new file %s", f.relative_path)
                changes += 1

            # Remove rows for files that no longer exist.
            for path in set(existing.keys()) - seen_paths:
                session.delete(existing[path])
                logger.info("Removed index entry for deleted file %s", path)
                changes += 1

        logger.info(
            "Sync complete: %d change(s), %d file(s) in dataset.",
            changes,
            len(files),
        )
        return changes
