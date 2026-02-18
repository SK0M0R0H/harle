"""Tests for harle.context — tokenizer and context assembler."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock

import pytest

from harle.context.assembler import (
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_INPUT_RATIO,
    DEFAULT_MAX_SEARCH_RESULTS,
    ContextAssembler,
    ContextPackage,
)
from harle.context.tokenizer import count_tokens
from harle.dataset.reader import DatasetReader
from harle.search.types import SearchResult


# ── Helpers ────────────────────────────────────────────────────────────


def _make_search_result(
    file_path: str = "knowledge/work/note.md",
    title: str = "Note",
    score: float = 5.0,
    context: str | None = "work",
    tags: list[str] | None = None,
    snippet: str | None = "A short snippet.",
) -> SearchResult:
    return SearchResult(
        file_path=file_path,
        title=title,
        score=score,
        context=context,
        tags=tags if tags is not None else ["test"],
        snippet=snippet,
    )


def _write_vault_file(
    root: Path,
    relative_path: str,
    *,
    title: str = "Untitled",
    tags: list[str] | None = None,
    context: str = "global",
    body: str = "Body content.",
) -> Path:
    """Create a Markdown file with YAML frontmatter inside *root*."""
    tags = tags or []
    tags_yaml = "\n".join(f"  - {t}" for t in tags) if tags else ""
    fm_tags = f"tags:\n{tags_yaml}" if tags else "tags: []"
    content = dedent(f"""\
        ---
        title: "{title}"
        {fm_tags}
        context: {context}
        ---
        {body}
    """)
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _assemble_without_dependencies(context: str = "work") -> ContextPackage:
    """Assemble context using the default no-dependency path."""
    return ContextAssembler().assemble(message="hello", context=context)


# ══════════════════════════════════════════════════════════════════════
# Tokenizer
# ══════════════════════════════════════════════════════════════════════


class TestCountTokens:
    def test_returns_positive_int(self) -> None:
        assert count_tokens("hello world") > 0

    def test_empty_string(self) -> None:
        assert count_tokens("") == 0

    def test_longer_text_has_more_tokens(self) -> None:
        short = count_tokens("hi")
        long = count_tokens("This is a much longer sentence with many words.")
        assert long > short

    def test_deterministic(self) -> None:
        text = "The quick brown fox jumps over the lazy dog."
        assert count_tokens(text) == count_tokens(text)

    def test_unicode(self) -> None:
        assert count_tokens("Привет мир 🌍") > 0

    def test_custom_encoding(self) -> None:
        text = "hello world"
        result = count_tokens(text, encoding_name="cl100k_base")
        assert result > 0


# ══════════════════════════════════════════════════════════════════════
# ContextPackage dataclass
# ══════════════════════════════════════════════════════════════════════


class TestContextPackage:
    def test_frozen(self) -> None:
        pkg = ContextPackage(system_prompt="prompt")
        with pytest.raises(AttributeError):
            pkg.system_prompt = "changed"  # type: ignore[misc]

    def test_defaults(self) -> None:
        pkg = ContextPackage(system_prompt="prompt")
        assert pkg.system_prompt == "prompt"
        assert pkg.search_results == []
        assert pkg.p0_files == []
        assert pkg.total_tokens == 0
        assert pkg.budget_remaining == 0

    def test_all_fields(self) -> None:
        result = _make_search_result()
        pkg = ContextPackage(
            system_prompt="sys",
            search_results=[result],
            p0_files=["prompts/agent.md"],
            total_tokens=100,
            budget_remaining=500,
        )
        assert pkg.search_results == [result]
        assert pkg.p0_files == ["prompts/agent.md"]
        assert pkg.total_tokens == 100
        assert pkg.budget_remaining == 500


# ══════════════════════════════════════════════════════════════════════
# ContextAssembler — initialisation and properties
# ══════════════════════════════════════════════════════════════════════


class TestContextAssemblerInit:
    def test_defaults(self) -> None:
        asm = ContextAssembler()
        assert asm.search_engine is None
        assert asm.dataset_reader is None
        assert asm.context_window == DEFAULT_CONTEXT_WINDOW
        assert asm.input_ratio == DEFAULT_INPUT_RATIO
        assert asm.max_search_results == DEFAULT_MAX_SEARCH_RESULTS

    def test_custom_window_and_ratio(self) -> None:
        asm = ContextAssembler(context_window=10_000, input_ratio=0.5)
        assert asm.context_window == 10_000
        assert asm.input_ratio == 0.5

    def test_token_budget_calculation(self) -> None:
        asm = ContextAssembler(context_window=10_000, input_ratio=0.80)
        assert asm.token_budget == 8_000

    def test_token_budget_default(self) -> None:
        asm = ContextAssembler()
        assert asm.token_budget == int(DEFAULT_CONTEXT_WINDOW * DEFAULT_INPUT_RATIO)


# ══════════════════════════════════════════════════════════════════════
# ContextAssembler.assemble — no dependencies
# ══════════════════════════════════════════════════════════════════════


class TestAssembleNoDependencies:
    """Assembler with no search engine and no dataset reader."""

    @pytest.fixture()
    def pkg(self) -> ContextPackage:
        return _assemble_without_dependencies("work")

    def test_package_shape_and_identity(self, pkg: ContextPackage) -> None:
        assert isinstance(pkg, ContextPackage)
        assert "Harle" in pkg.system_prompt
        assert "work" in pkg.system_prompt
        assert pkg.search_results == []
        assert pkg.p0_files == []

    @pytest.mark.parametrize("context", ["work", "personal"])
    def test_context_scope_in_prompt(self, context: str) -> None:
        pkg = _assemble_without_dependencies(context=context)
        assert context in pkg.system_prompt

    def test_token_accounting(self, pkg: ContextPackage) -> None:
        asm = ContextAssembler()
        assert pkg.total_tokens > 0
        assert pkg.budget_remaining > 0
        assert pkg.total_tokens + pkg.budget_remaining == asm.token_budget


# ══════════════════════════════════════════════════════════════════════
# ContextAssembler.assemble — P0 loading (dataset reader only)
# ══════════════════════════════════════════════════════════════════════


class TestAssembleP0:
    """P0 loading: prompts/ and policies/ from a real dataset reader."""

    @staticmethod
    def _assemble(vault: Path, *, context: str = "work") -> ContextPackage:
        reader = DatasetReader(str(vault))
        asm = ContextAssembler(dataset_reader=reader)
        return asm.assemble(message="hello", context=context)

    @pytest.fixture()
    def vault(self, tmp_path: Path) -> Path:
        """Vault with prompts and policies."""
        _write_vault_file(
            tmp_path,
            "prompts/secretary.md",
            title="Secretary Prompt",
            tags=["prompt", "secretary"],
            context="global",
            body="You are a secretary agent.",
        )
        _write_vault_file(
            tmp_path,
            "policies/privacy.md",
            title="Privacy Policy",
            tags=["policy", "privacy"],
            context="global",
            body="Never share personal data.",
        )
        _write_vault_file(
            tmp_path,
            "knowledge/work/notes.md",
            title="Work Notes",
            tags=["knowledge"],
            context="work",
            body="Some work notes.",
        )
        return tmp_path

    def test_loads_prompts(self, vault: Path) -> None:
        pkg = self._assemble(vault)
        assert "prompts/secretary.md" in pkg.p0_files
        assert "Secretary Prompt" in pkg.system_prompt

    def test_loads_policies(self, vault: Path) -> None:
        pkg = self._assemble(vault)
        assert "policies/privacy.md" in pkg.p0_files
        assert "Privacy Policy" in pkg.system_prompt

    def test_excludes_knowledge_from_p0(self, vault: Path) -> None:
        pkg = self._assemble(vault)
        assert "knowledge/work/notes.md" not in pkg.p0_files

    def test_prompt_section_before_policies(self, vault: Path) -> None:
        pkg = self._assemble(vault)
        prompt_pos = pkg.system_prompt.index("Agent Roles")
        policy_pos = pkg.system_prompt.index("Active Policies")
        assert prompt_pos < policy_pos

    def test_identity_at_beginning(self, vault: Path) -> None:
        pkg = self._assemble(vault)
        assert pkg.system_prompt.startswith("You are Harle")


class TestAssembleP0ContextFiltering:
    @staticmethod
    def _assemble(vault: Path, *, context: str) -> ContextPackage:
        reader = DatasetReader(str(vault))
        asm = ContextAssembler(dataset_reader=reader)
        return asm.assemble(message="hi", context=context)

    """P0 files are filtered by context scope."""

    @pytest.fixture()
    def vault(self, tmp_path: Path) -> Path:
        _write_vault_file(
            tmp_path,
            "prompts/global-agent.md",
            title="Global Agent",
            context="global",
            body="Global agent body.",
        )
        _write_vault_file(
            tmp_path,
            "prompts/work-agent.md",
            title="Work Agent",
            context="work",
            body="Work-only agent body.",
        )
        _write_vault_file(
            tmp_path,
            "prompts/personal-agent.md",
            title="Personal Agent",
            context="personal",
            body="Personal-only agent body.",
        )
        _write_vault_file(
            tmp_path,
            "policies/work-policy.md",
            title="Work Policy",
            context="work",
            body="Work-only policy.",
        )
        return tmp_path

    def test_global_files_always_included(self, vault: Path) -> None:
        work_pkg = self._assemble(vault, context="work")
        personal_pkg = self._assemble(vault, context="personal")

        assert "prompts/global-agent.md" in work_pkg.p0_files
        assert "prompts/global-agent.md" in personal_pkg.p0_files

    def test_matching_context_included(self, vault: Path) -> None:
        pkg = self._assemble(vault, context="work")
        assert "prompts/work-agent.md" in pkg.p0_files
        assert "policies/work-policy.md" in pkg.p0_files

    def test_mismatched_context_excluded(self, vault: Path) -> None:
        pkg = self._assemble(vault, context="work")
        assert "prompts/personal-agent.md" not in pkg.p0_files

    def test_no_context_file_included(self, tmp_path: Path) -> None:
        """Files without a context field are included for any scope."""
        (tmp_path / "prompts").mkdir()
        (tmp_path / "prompts" / "no-ctx.md").write_text(
            dedent("""\
                ---
                title: No Context
                tags: [prompt]
                ---
                Agent with no context field.
            """),
            encoding="utf-8",
        )
        reader = DatasetReader(str(tmp_path))
        asm = ContextAssembler(dataset_reader=reader)
        pkg = asm.assemble(message="hi", context="work")

        assert "prompts/no-ctx.md" in pkg.p0_files


# ══════════════════════════════════════════════════════════════════════
# ContextAssembler.assemble — P1 loading (search results)
# ══════════════════════════════════════════════════════════════════════


class TestAssembleP1:
    """P1 loading via a mocked search engine."""

    def _mock_engine(self, results: list[SearchResult]) -> MagicMock:
        engine = MagicMock()
        engine.search.return_value = results
        return engine

    def test_includes_search_results(self) -> None:
        result = _make_search_result(
            file_path="knowledge/work/note.md",
            title="Work Note",
        )
        engine = self._mock_engine([result])
        asm = ContextAssembler(search_engine=engine)
        pkg = asm.assemble(message="find notes", context="work")

        assert len(pkg.search_results) == 1
        assert pkg.search_results[0].file_path == "knowledge/work/note.md"

    def test_search_results_appear_in_prompt(self) -> None:
        result = _make_search_result(title="Important File")
        engine = self._mock_engine([result])
        asm = ContextAssembler(search_engine=engine)
        pkg = asm.assemble(message="find stuff", context="work")

        assert "Important File" in pkg.system_prompt
        assert "Relevant Dataset Files" in pkg.system_prompt

    def test_snippet_used_when_no_reader(self) -> None:
        result = _make_search_result(snippet="this is the snippet text")
        engine = self._mock_engine([result])
        asm = ContextAssembler(search_engine=engine, dataset_reader=None)
        pkg = asm.assemble(message="test", context="work")

        assert "this is the snippet text" in pkg.system_prompt

    def test_full_content_loaded_when_reader_available(self, tmp_path: Path) -> None:
        _write_vault_file(
            tmp_path,
            "knowledge/work/data.md",
            title="Data File",
            context="work",
            body="Full body content of the data file.",
        )
        result = _make_search_result(
            file_path="knowledge/work/data.md",
            title="Data File",
            snippet="short snippet",
        )
        engine = self._mock_engine([result])
        reader = DatasetReader(str(tmp_path))
        asm = ContextAssembler(search_engine=engine, dataset_reader=reader)
        pkg = asm.assemble(message="data", context="work")

        assert "Full body content of the data file" in pkg.system_prompt

    def test_empty_search_results(self) -> None:
        engine = self._mock_engine([])
        asm = ContextAssembler(search_engine=engine)
        pkg = asm.assemble(message="nothing", context="work")

        assert pkg.search_results == []
        assert "Relevant Dataset Files" not in pkg.system_prompt

    def test_search_engine_receives_correct_query(self) -> None:
        engine = self._mock_engine([])
        asm = ContextAssembler(search_engine=engine, max_search_results=5)
        asm.assemble(message="find tasks", context="work")

        engine.search.assert_called_once()
        query = engine.search.call_args[0][0]
        assert query.query == "find tasks"
        assert query.context == "work"
        assert query.max_results == 5

    def test_tags_appear_in_prompt(self) -> None:
        result = _make_search_result(tags=["python", "testing"])
        engine = self._mock_engine([result])
        asm = ContextAssembler(search_engine=engine)
        pkg = asm.assemble(message="test", context="work")

        assert "python" in pkg.system_prompt
        assert "testing" in pkg.system_prompt

    def test_no_tags_line_when_empty(self) -> None:
        result = _make_search_result(tags=[])
        engine = self._mock_engine([result])
        asm = ContextAssembler(search_engine=engine)
        pkg = asm.assemble(message="test", context="work")

        assert "Tags:" not in pkg.system_prompt


# ══════════════════════════════════════════════════════════════════════
# ContextAssembler — P0/P1 deduplication
# ══════════════════════════════════════════════════════════════════════


class TestAssembleDeduplication:
    """P0 files are excluded from P1 search results."""

    def test_p0_file_excluded_from_search_results(self, tmp_path: Path) -> None:
        _write_vault_file(
            tmp_path,
            "prompts/agent.md",
            title="Agent Prompt",
            context="global",
            body="Agent identity.",
        )
        p0_result = _make_search_result(
            file_path="prompts/agent.md",
            title="Agent Prompt",
        )
        other_result = _make_search_result(
            file_path="knowledge/work/note.md",
            title="Work Note",
        )
        engine = MagicMock()
        engine.search.return_value = [p0_result, other_result]

        reader = DatasetReader(str(tmp_path))
        asm = ContextAssembler(search_engine=engine, dataset_reader=reader)
        pkg = asm.assemble(message="agent", context="work")

        result_paths = [r.file_path for r in pkg.search_results]
        assert "prompts/agent.md" not in result_paths
        assert "knowledge/work/note.md" in result_paths


# ══════════════════════════════════════════════════════════════════════
# ContextAssembler — token budget enforcement
# ══════════════════════════════════════════════════════════════════════


class TestAssembleTokenBudget:
    """Budget enforcement limits how many search results are included."""

    def test_budget_tracked(self) -> None:
        asm = ContextAssembler(context_window=10_000, input_ratio=0.80)
        pkg = asm.assemble(message="hi", context="work")

        assert pkg.total_tokens > 0
        assert pkg.budget_remaining == 8_000 - pkg.total_tokens

    def test_very_tight_budget_still_returns_p0(self) -> None:
        """Even with a tiny budget, the base identity prompt is present."""
        asm = ContextAssembler(context_window=200, input_ratio=1.0)
        pkg = asm.assemble(message="hi", context="work")

        assert "Harle" in pkg.system_prompt
        assert pkg.total_tokens > 0

    def test_tight_budget_limits_search_results(self) -> None:
        """With a small budget, not all search results fit."""
        long_snippet = "word " * 200
        results = [
            _make_search_result(
                file_path=f"knowledge/file{i}.md",
                title=f"File {i}",
                snippet=long_snippet,
            )
            for i in range(10)
        ]
        engine = MagicMock()
        engine.search.return_value = results

        # Tight budget — only a few results should fit.
        asm = ContextAssembler(
            search_engine=engine,
            context_window=1_000,
            input_ratio=1.0,
        )
        pkg = asm.assemble(message="test", context="work")

        assert len(pkg.search_results) < 10

    def test_budget_not_exceeded(self) -> None:
        long_snippet = "word " * 100
        results = [
            _make_search_result(
                file_path=f"knowledge/file{i}.md",
                title=f"File {i}",
                snippet=long_snippet,
            )
            for i in range(5)
        ]
        engine = MagicMock()
        engine.search.return_value = results

        asm = ContextAssembler(
            search_engine=engine,
            context_window=2_000,
            input_ratio=0.80,
        )
        pkg = asm.assemble(message="test", context="work")

        assert pkg.total_tokens <= asm.token_budget


# ══════════════════════════════════════════════════════════════════════
# ContextAssembler._format_p0 (static method, tested directly)
# ══════════════════════════════════════════════════════════════════════


class TestFormatP0:
    """Direct tests for the P0 formatting static method."""

    def test_empty_files(self) -> None:
        text = ContextAssembler._format_p0([], context="work")
        assert "Harle" in text
        assert "work" in text
        assert "Agent Roles" not in text
        assert "Active Policies" not in text

    def test_prompt_file_creates_roles_section(self) -> None:
        from harle.dataset.reader import DatasetFile

        prompt = DatasetFile(
            relative_path="prompts/researcher.md",
            title="Researcher",
            content="You are a researcher.",
        )
        text = ContextAssembler._format_p0([prompt], context="work")

        assert "## Agent Roles" in text
        assert "### Researcher" in text
        assert "You are a researcher." in text

    def test_policy_file_creates_policies_section(self) -> None:
        from harle.dataset.reader import DatasetFile

        policy = DatasetFile(
            relative_path="policies/privacy.md",
            title="Privacy",
            content="Do not share data.",
        )
        text = ContextAssembler._format_p0([policy], context="personal")

        assert "## Active Policies" in text
        assert "### Privacy" in text
        assert "Do not share data." in text

    def test_file_without_title_uses_path(self) -> None:
        from harle.dataset.reader import DatasetFile

        prompt = DatasetFile(
            relative_path="prompts/no-title.md",
            title=None,
            content="Content here.",
        )
        text = ContextAssembler._format_p0([prompt], context="work")

        assert "### prompts/no-title.md" in text


# ══════════════════════════════════════════════════════════════════════
# ContextAssembler._format_search_results
# ══════════════════════════════════════════════════════════════════════


class TestFormatSearchResults:
    """Direct tests for search result formatting."""

    def test_empty_results(self) -> None:
        asm = ContextAssembler()
        text, included = asm._format_search_results(
            results=[], budget_remaining=10_000
        )
        assert text == ""
        assert included == []

    def test_single_result(self) -> None:
        asm = ContextAssembler()
        result = _make_search_result(title="My File", snippet="content here")
        text, included = asm._format_search_results(
            results=[result], budget_remaining=10_000
        )

        assert len(included) == 1
        assert "My File" in text
        assert "## Relevant Dataset Files" in text

    def test_zero_budget_returns_empty(self) -> None:
        asm = ContextAssembler()
        result = _make_search_result()
        text, included = asm._format_search_results(
            results=[result], budget_remaining=0
        )
        assert text == ""
        assert included == []

    def test_budget_limits_results(self) -> None:
        asm = ContextAssembler()
        results = [
            _make_search_result(
                file_path=f"f{i}.md",
                title=f"File {i}",
                snippet="x " * 200,
            )
            for i in range(20)
        ]
        # Small budget: header + maybe one result
        text, included = asm._format_search_results(
            results=results, budget_remaining=300
        )
        assert len(included) < 20


# ══════════════════════════════════════════════════════════════════════
# ContextAssembler._render_result_entry
# ══════════════════════════════════════════════════════════════════════


class TestRenderResultEntry:
    def test_snippet_mode(self) -> None:
        asm = ContextAssembler()
        result = _make_search_result(
            title="My Note",
            file_path="knowledge/note.md",
            tags=["python"],
            snippet="Some snippet text.",
        )
        entry = asm._render_result_entry(result, full_content=False)

        assert "### My Note (knowledge/note.md)" in entry
        assert "Tags: python" in entry
        assert "Some snippet text." in entry

    def test_full_content_mode_with_reader(self, tmp_path: Path) -> None:
        _write_vault_file(
            tmp_path,
            "knowledge/note.md",
            title="My Note",
            body="Full body text from file.",
        )
        reader = DatasetReader(str(tmp_path))
        asm = ContextAssembler(dataset_reader=reader)
        result = _make_search_result(
            file_path="knowledge/note.md",
            title="My Note",
            snippet="snippet fallback",
        )
        entry = asm._render_result_entry(result, full_content=True)

        assert "Full body text from file." in entry

    def test_full_content_falls_back_to_snippet(self) -> None:
        """When reader is None, full_content=True falls back to snippet."""
        asm = ContextAssembler(dataset_reader=None)
        result = _make_search_result(snippet="fallback snippet")
        entry = asm._render_result_entry(result, full_content=True)

        assert "fallback snippet" in entry

    def test_no_tags_omits_tags_line(self) -> None:
        asm = ContextAssembler()
        result = _make_search_result(tags=[])
        entry = asm._render_result_entry(result, full_content=False)

        assert "Tags:" not in entry

    def test_no_snippet_uses_empty_body(self) -> None:
        asm = ContextAssembler()
        result = _make_search_result(snippet=None)
        entry = asm._render_result_entry(result, full_content=False)

        assert "### " in entry


# ══════════════════════════════════════════════════════════════════════
# ContextAssembler._load_file_content
# ══════════════════════════════════════════════════════════════════════


class TestLoadFileContent:
    def test_no_reader_returns_none(self) -> None:
        asm = ContextAssembler(dataset_reader=None)
        assert asm._load_file_content("any/file.md") is None

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        reader = DatasetReader(str(tmp_path))
        asm = ContextAssembler(dataset_reader=reader)
        assert asm._load_file_content("nonexistent.md") is None

    def test_valid_file_returns_body(self, tmp_path: Path) -> None:
        _write_vault_file(
            tmp_path,
            "knowledge/note.md",
            title="Note",
            body="The actual body.",
        )
        reader = DatasetReader(str(tmp_path))
        asm = ContextAssembler(dataset_reader=reader)
        content = asm._load_file_content("knowledge/note.md")

        assert content is not None
        assert "The actual body." in content


# ══════════════════════════════════════════════════════════════════════
# End-to-end integration
# ══════════════════════════════════════════════════════════════════════


class TestAssembleEndToEnd:
    """Full integration with real dataset reader and mocked search engine."""

    @pytest.fixture()
    def vault(self, tmp_path: Path) -> Path:
        _write_vault_file(
            tmp_path,
            "prompts/secretary.md",
            title="Secretary",
            tags=["prompt", "secretary"],
            context="global",
            body="You are a secretary agent. Manage tasks.",
        )
        _write_vault_file(
            tmp_path,
            "policies/privacy.md",
            title="Privacy",
            tags=["policy", "privacy"],
            context="global",
            body="Respect user privacy at all times.",
        )
        _write_vault_file(
            tmp_path,
            "knowledge/work/tasks.md",
            title="Task List",
            tags=["tasks", "work"],
            context="work",
            body="Task 1: Build context assembler. Task 2: Write tests.",
        )
        return tmp_path

    def test_full_assembly_with_search(self, vault: Path) -> None:
        reader = DatasetReader(str(vault))
        search_result = _make_search_result(
            file_path="knowledge/work/tasks.md",
            title="Task List",
            tags=["tasks", "work"],
            snippet="Task 1: Build context assembler.",
        )
        engine = MagicMock()
        engine.search.return_value = [search_result]

        asm = ContextAssembler(search_engine=engine, dataset_reader=reader)
        pkg = asm.assemble(message="show my tasks", context="work")

        # P0 files loaded.
        assert "prompts/secretary.md" in pkg.p0_files
        assert "policies/privacy.md" in pkg.p0_files

        # P1 search result loaded with full content.
        assert len(pkg.search_results) == 1
        assert "Task 1: Build context assembler. Task 2: Write tests." in pkg.system_prompt

        # Structural sections present.
        assert "Agent Roles" in pkg.system_prompt
        assert "Active Policies" in pkg.system_prompt
        assert "Relevant Dataset Files" in pkg.system_prompt

        # Token accounting.
        assert pkg.total_tokens > 0
        assert pkg.budget_remaining > 0
        assert pkg.total_tokens + pkg.budget_remaining == asm.token_budget
