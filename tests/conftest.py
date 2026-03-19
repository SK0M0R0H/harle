"""Shared fixtures for Harle unit tests."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from harle.db.connection import Database
from harle.db.models import Conversation, Message


def make_in_memory_chat_db() -> Database:
    """SQLite in-memory DB with conversation tables (for /chat unit tests).

    Uses :class:`StaticPool` so all connections (including worker threads)
    share one in-memory database. Run persistence is often patched out
    (``runs`` uses PostgreSQL ARRAY).
    """
    db = Database.__new__(Database)
    db.engine = create_engine(
        "sqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db._session_factory = sessionmaker(bind=db.engine, expire_on_commit=False)
    Conversation.__table__.create(db.engine, checkfirst=True)
    Message.__table__.create(db.engine, checkfirst=True)
    return db


# ---------------------------------------------------------------------------
# Temporary dataset directory
# ---------------------------------------------------------------------------

SAMPLE_MD_WITH_FRONTMATTER = dedent("""\
    ---
    title: Test Note
    tags:
      - python
      - testing
    context: work
    ---
    This is the body content of the test note.
    It has multiple lines of text.
""")

SAMPLE_MD_NO_FRONTMATTER = dedent("""\
    # Plain Note

    This file has no YAML frontmatter at all.
""")

SAMPLE_MD_PERSONAL = dedent("""\
    ---
    title: Personal Journal
    tags:
      - journal
    context: personal
    ---
    Today I learned about testing.
""")


@pytest.fixture()
def dataset_dir(tmp_path: Path) -> Path:
    """Create a temporary dataset directory with sample Markdown files."""
    # Top-level file
    (tmp_path / "note.md").write_text(SAMPLE_MD_WITH_FRONTMATTER, encoding="utf-8")
    (tmp_path / "plain.md").write_text(SAMPLE_MD_NO_FRONTMATTER, encoding="utf-8")
    (tmp_path / "journal.md").write_text(SAMPLE_MD_PERSONAL, encoding="utf-8")

    # Nested directory
    subdir = tmp_path / "sub"
    subdir.mkdir()
    (subdir / "nested.md").write_text(
        dedent("""\
            ---
            title: Nested File
            tags:
              - nested
            context: work
            ---
            Content inside a subdirectory.
        """),
        encoding="utf-8",
    )

    # Hidden directory (should be excluded by reader)
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "secret.md").write_text("# Secret\nHidden content.\n", encoding="utf-8")

    # Non-markdown file (should be ignored)
    (tmp_path / "readme.txt").write_text("Not a markdown file.\n", encoding="utf-8")

    return tmp_path
