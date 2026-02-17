"""Shared fixtures for Harle unit tests."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest


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
