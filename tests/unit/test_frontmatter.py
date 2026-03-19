"""Tests for harle.dataset.frontmatter — YAML frontmatter parser."""

from __future__ import annotations

import logging
from textwrap import dedent

import pytest

from harle.dataset.frontmatter import dump_frontmatter_fields, parse_frontmatter


class TestParseFrontmatter:
    def test_valid_frontmatter(self) -> None:
        content = dedent("""\
            ---
            title: My Note
            tags:
              - python
              - testing
            context: work
            ---
            Body content here.
        """)
        meta, body = parse_frontmatter(content)
        assert meta["title"] == "My Note"
        assert meta["tags"] == ["python", "testing"]
        assert meta["context"] == "work"
        assert body == "Body content here."

    def test_no_frontmatter(self) -> None:
        content = "# Just a heading\n\nSome text.\n"
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert body == content

    def test_unclosed_frontmatter(self) -> None:
        content = "---\ntitle: Oops\nNo closing fence\n"
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert body == content

    def test_empty_frontmatter(self) -> None:
        content = "---\n---\nBody after empty frontmatter.\n"
        meta, body = parse_frontmatter(content)
        # yaml.safe_load("") returns None, not a dict
        assert meta == {}
        assert body == content

    def test_frontmatter_with_only_title(self) -> None:
        content = "---\ntitle: Solo\n---\nText.\n"
        meta, body = parse_frontmatter(content)
        assert meta == {"title": "Solo"}
        assert body == "Text."

    def test_invalid_yaml_in_frontmatter(self) -> None:
        content = "---\n: invalid: yaml: here\n---\nBody.\n"
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert body == content

    def test_invalid_yaml_logs_source_path(self, caplog: pytest.LogCaptureFixture) -> None:
        content = "---\n: invalid: yaml: here\n---\nBody.\n"
        caplog.set_level(logging.WARNING)
        meta, body = parse_frontmatter(content, source_path="notes/broken.md")
        assert meta == {}
        assert body == content
        assert any("notes/broken.md" in r.message for r in caplog.records)

    def test_non_dict_frontmatter(self) -> None:
        content = "---\n- item1\n- item2\n---\nBody.\n"
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert body == content

    def test_multiline_body(self) -> None:
        content = dedent("""\
            ---
            title: Multi
            ---
            Line one.

            Line two.

            Line three.
        """)
        meta, body = parse_frontmatter(content)
        assert meta["title"] == "Multi"
        assert "Line one." in body
        assert "Line three." in body

    def test_content_not_starting_with_dashes(self) -> None:
        content = "No dashes at start.\n---\nThis is not frontmatter.\n"
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert body == content

    def test_empty_content(self) -> None:
        meta, body = parse_frontmatter("")
        assert meta == {}
        assert body == ""


class TestDumpFrontmatterFields:
    def test_float_and_list_values_use_json(self) -> None:
        raw = dump_frontmatter_fields({"score": 0.5, "items": [1, 2]})
        assert "0.5" in raw
        assert "[1, 2]" in raw or "1, 2" in raw

    def test_bool_and_none_scalars(self) -> None:
        assert "true" in dump_frontmatter_fields({"flag": True})
        assert "false" in dump_frontmatter_fields({"flag": False})
        assert "null" in dump_frontmatter_fields({"empty": None})

    def test_colon_in_string_value_round_trips_via_parse(self) -> None:
        raw = dump_frontmatter_fields(
            {"run_id": "Tool: notion_search", "total_spans": 3}
        )
        wrapped = f"---\n{raw}\n---\n\nbody\n"
        meta, body = parse_frontmatter(wrapped)
        assert meta["run_id"] == "Tool: notion_search"
        assert meta["total_spans"] == 3
        assert body == "body"
