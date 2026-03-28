"""Integration tests: chunking pipeline (Whoosh → rank) and assembler chunk load."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harle.api.processing_registry import build_processing_registry
from harle.api.routes import build_router
from harle.context.assembler import ContextAssembler
from harle.llm.providers import EchoProvider
from harle.orchestrator.service import OrchestratorService
from harle.dataset.reader import DatasetReader
from harle.search.query_expander import expand
from harle.search.ranker import rank
from harle.search.types import (
    QueryMetadata,
    SearchQuery,
    SearchResponse,
    SearchResult,
)
from harle.search import whoosh_index


def _workflow_body(unique: str) -> str:
    return f"""---
title: Integration Chunk Workflow
tags: [integration]
context: work
---

## Alpha

Alpha only.

## Beta

{unique}
"""


@pytest.mark.integration
class TestChunkingWhooshPipeline:
    """Whoosh build → search → rank yields chunk metadata for workflows/."""

    def test_ranked_hit_has_chunk_index_for_matching_section(self, tmp_path: Path) -> None:
        token = "unique_integration_chunk_token_beta_99"
        wf = tmp_path / "workflows" / "chunky.md"
        wf.parent.mkdir(parents=True)
        wf.write_text(_workflow_body(token), encoding="utf-8")

        reader = DatasetReader(str(tmp_path))
        whoosh_index.build_from_scratch(reader, tmp_path / "whoosh_idx")

        config = SimpleNamespace(
            add_role_terms=False,
            match_tag_vocabulary=True,
            use_stemming=True,
        )
        query = SearchQuery(query=token, context="work", max_results=10)
        expanded = expand(query, {"integration", "work"}, config)
        assert expanded.whoosh_terms

        hits = whoosh_index.search(
            tmp_path / "whoosh_idx",
            expanded.whoosh_terms,
            {"workflows/chunky.md"},
            limit=10,
        )
        assert hits
        chunk_hits = [h for h in hits if h.chunk_index is not None]
        assert chunk_hits, "expected a composite Whoosh doc for the Beta section"

        path_to_metadata = {
            "workflows/chunky.md": SimpleNamespace(
                file_path="workflows/chunky.md",
                title="Integration Chunk Workflow",
                tags=["integration"],
                context="work",
                token_count=None,
                summary=None,
                last_modified=None,
            ),
        }
        ranked = rank(
            chunk_hits,
            path_to_metadata,
            tag_filters=[],
            max_chunks_per_file=5,
        )
        assert ranked
        top = ranked[0]
        assert top.file_path == "workflows/chunky.md"
        assert top.chunk_index is not None
        assert top.heading_path and "Beta" in top.heading_path


@pytest.mark.integration
class TestSearchApiChunkMetadata:
    """GET /search exposes chunk_index and heading_path from SearchResult."""

    def test_search_response_includes_chunk_fields(self) -> None:
        class _EngineWithChunk:
            def search(self, query: SearchQuery) -> SearchResponse:
                return SearchResponse(
                    file_results=[
                        SearchResult(
                            file_path="workflows/demo.md",
                            title="Demo",
                            score=0.9,
                            context="work",
                            tags=[],
                            snippet=None,
                            chunk_index=1,
                            heading_path="Demo > Beta",
                        )
                    ],
                    memory_results=[],
                    prior_runs=[],
                    query_metadata=QueryMetadata(
                        original_query=query.query,
                        expanded_terms=[],
                        tags_matched=[],
                        candidates_count=1,
                        search_time_ms=0.0,
                        phase="stub",
                    ),
                )

        app = FastAPI()
        app.include_router(
            build_router(
                orchestrator=OrchestratorService(llm_provider=EchoProvider()),
                processing_registry=build_processing_registry(run_timeout_seconds=60),
                search_engine=_EngineWithChunk(),
            )
        )
        client = TestClient(app)
        response = client.get("/search", params={"q": "beta", "context": "work"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        row = data["results"][0]
        assert row["file_path"] == "workflows/demo.md"
        assert row["chunk_index"] == 1
        assert row["heading_path"] == "Demo > Beta"


@pytest.mark.integration
class TestChunkingContextAssembler:
    """Assembler resolves chunk_index via deterministic re-chunk and adds excerpt hint."""

    def test_excerpt_hint_and_section_body_in_system_prompt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        token = "unique_assembler_chunk_token_zeta_42"
        rel = "workflows/assembler-chunk.md"
        p = tmp_path / rel
        p.parent.mkdir(parents=True)
        p.write_text(_workflow_body(token), encoding="utf-8")

        class _Engine:
            def search(self, query: SearchQuery) -> SearchResponse:
                return SearchResponse(
                    file_results=[
                        SearchResult(
                            file_path=rel,
                            title="Integration Chunk Workflow",
                            score=1.0,
                            context="work",
                            tags=["integration"],
                            snippet=None,
                            chunk_index=1,
                            heading_path="Integration Chunk Workflow > Beta",
                        )
                    ],
                    memory_results=[],
                    prior_runs=[],
                    query_metadata=QueryMetadata(
                        original_query=query.query,
                        expanded_terms=[],
                        tags_matched=[],
                        candidates_count=1,
                        search_time_ms=0.0,
                        phase="stub",
                    ),
                )

        reader = DatasetReader(str(tmp_path))
        assembler = ContextAssembler(
            search_engine=_Engine(),
            dataset_reader=reader,
            max_search_results=5,
        )

        monkeypatch.setattr(
            "harle.context.assembler.count_tokens",
            lambda text: max(1, len(text.split())),
        )
        pkg = assembler.assemble(
            message=f"find {token}",
            context="work",
            agent_role="researcher",
        )

        assert token in pkg.system_prompt
        assert "_Excerpt from`" in pkg.system_prompt or "Excerpt from" in pkg.system_prompt
        assert rel in pkg.system_prompt
        assert "## Beta" in pkg.system_prompt or token in pkg.system_prompt
