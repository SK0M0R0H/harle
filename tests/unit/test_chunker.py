"""Tests for harle.indexing.chunker."""

from __future__ import annotations

from harle.indexing.chunker import (
    ChunkStrategy,
    chunk_file,
    get_strategy,
    parse_whoosh_doc_path,
    whoosh_doc_path,
)


class TestGetStrategy:
    def test_prompts_always_whole(self) -> None:
        assert get_strategy("prompts/x.md", 10_000) == ChunkStrategy.WHOLE

    def test_policies_always_whole(self) -> None:
        assert get_strategy("policies/p.md", 10_000) == ChunkStrategy.WHOLE

    def test_examples_whole(self) -> None:
        assert get_strategy("examples/e.md", 10_000) == ChunkStrategy.WHOLE

    def test_workflows_section(self) -> None:
        assert get_strategy("workflows/w.md", 100) == ChunkStrategy.SECTION_H2

    def test_knowledge_short_whole(self) -> None:
        assert get_strategy("knowledge/work/x.md", 500) == ChunkStrategy.WHOLE

    def test_knowledge_long_section(self) -> None:
        assert get_strategy("knowledge/work/x.md", 2500) == ChunkStrategy.SECTION_H2

    def test_logs_paragraph(self) -> None:
        assert get_strategy("logs/2026/01/run.md", 100) == ChunkStrategy.PARAGRAPH

    def test_disabled_chunking(self) -> None:
        assert (
            get_strategy("workflows/w.md", 10_000, chunking_enabled=False)
            == ChunkStrategy.WHOLE
        )


class TestSectionH2Chunks:
    def test_splits_at_h2(self) -> None:
        body = """# Doc Title

Intro line.

## Alpha

alpha content

## Beta

beta content
"""
        chunks = chunk_file(
            content=body,
            title="FM Title",
            tags=["t"],
            context="work",
            relative_path="workflows/w.md",
            strategy=ChunkStrategy.SECTION_H2,
            contextual_enrichment=False,
        )
        assert len(chunks) == 3
        assert chunks[0].chunk_index == 0
        assert "Intro" in chunks[0].content or "Intro line" in chunks[0].content
        assert chunks[1].heading_path == "FM Title > Alpha"
        assert "alpha content" in chunks[1].content
        assert chunks[2].heading_path == "FM Title > Beta"

    def test_no_h2_falls_back_to_single_chunk(self) -> None:
        body = "# Only H1\n\nno h2 here."
        chunks = chunk_file(
            content=body,
            title=None,
            tags=[],
            context=None,
            relative_path="workflows/w.md",
            strategy=ChunkStrategy.SECTION_H2,
            contextual_enrichment=False,
        )
        assert len(chunks) == 1
        assert chunks[0].chunk_index == 0


class TestWhooshDocPath:
    def test_single_chunk_uses_plain_path(self) -> None:
        assert whoosh_doc_path("k/x.md", 0, 1) == "k/x.md"

    def test_multi_uses_composite(self) -> None:
        assert whoosh_doc_path("k/x.md", 1, 3) == "k/x.md#1"

    def test_parse_composite(self) -> None:
        assert parse_whoosh_doc_path("k/x.md#2") == ("k/x.md", 2)

    def test_parse_plain(self) -> None:
        assert parse_whoosh_doc_path("k/x.md") == ("k/x.md", None)
