"""Priority-based context assembly with token budgeting.

The Context Assembler gathers all information the agent needs before
calling the LLM.  It loads agent prompts and policies (P0), searches
the dataset for relevant files (P1), and packs everything into a
token-budgeted context package that fits within the model's context
window.

Design follows ``docs/trd/architecture/orchestrator.md`` section 4 and
the best-practices recommendations in
``docs/trd/architecture/data_layer_best_practices.md`` sections 4.1–4.3.

Budget rule: ~80 % for input context, ~20 % reserved for the model's
response.  P0 content is always included; P1 content is added until
the budget is exhausted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from harle.config import get_chunking_config
from harle.context.tokenizer import count_tokens
from harle.dataset.reader import DatasetFile, DatasetReader
from harle.indexing.chunker import chunk_file, get_strategy
from harle.debug import etrace
from harle.search.engine import SearchEngine
from harle.search.types import SearchQuery, SearchResult

logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────
DEFAULT_CONTEXT_WINDOW: int = 128_000
DEFAULT_INPUT_RATIO: float = 0.80
DEFAULT_MAX_SEARCH_RESULTS: int = 10

# Vault directories whose files are always loaded as P0.
_P0_DIRECTORIES: tuple[str, ...] = ("prompts/", "policies/")


def _prompt_file_matches_role(relative_path: str, role: str) -> bool:
    """Check if a prompt file's stem matches the given role name.

    ``prompts/secretary.md`` matches role ``"secretary"``.
    """
    stem = relative_path.split("/")[-1].removesuffix(".md")
    return stem == role


# ── Data structures ───────────────────────────────────────────────────


@dataclass(frozen=True)
class ContextPackage:
    """Assembled context ready to be sent to the LLM.

    Attributes:
        system_prompt: Complete system prompt including agent identity,
            policies, and relevant dataset content.
        search_results: Dataset search results that were included in
            the context.
        p0_files: Prompt and policy files loaded as mandatory context.
        total_tokens: Estimated token count of the assembled context.
        budget_remaining: Tokens remaining before hitting the budget.
        conversation_messages_included: Number of conversation history
            messages included in the context (P4).
    """

    system_prompt: str
    search_results: list[SearchResult] = field(default_factory=list)
    p0_files: list[str] = field(default_factory=list)
    total_tokens: int = 0
    budget_remaining: int = 0
    conversation_messages_included: int = 0


# ── Assembler ─────────────────────────────────────────────────────────


class ContextAssembler:
    """Gather, prioritise, and pack context for an LLM request.

    Priority levels (from TRD section 4):

    * **P0 (mandatory):** Agent prompts + policies — always included.
    * **P1 (critical):** Dataset search results — added within budget.

    Higher-priority tiers (P2–P4: external data, memories,
    conversation history) are not yet implemented and will be added
    as the corresponding modules become available.

    Args:
        search_engine: Search engine for querying the indexed dataset.
            May be ``None`` if the data layer is not configured.
        dataset_reader: Reader for loading Markdown files from the
            vault.  May be ``None`` if the dataset path is not set.
        context_window: Total model context window in tokens.
        input_ratio: Fraction of context window allocated to input
            (0.0–1.0).  The remainder is reserved for the model's
            response.
        max_search_results: Maximum number of search results to
            consider for P1 inclusion.
    """

    def __init__(
        self,
        search_engine: SearchEngine | None = None,
        dataset_reader: DatasetReader | None = None,
        *,
        context_window: int = DEFAULT_CONTEXT_WINDOW,
        input_ratio: float = DEFAULT_INPUT_RATIO,
        max_search_results: int = DEFAULT_MAX_SEARCH_RESULTS,
    ) -> None:
        self.search_engine = search_engine
        self.dataset_reader = dataset_reader
        self.context_window = context_window
        self.input_ratio = input_ratio
        self.max_search_results = max_search_results

    # ── public API ────────────────────────────────────────────────────

    @property
    def token_budget(self) -> int:
        """Maximum tokens available for the input context."""
        return int(self.context_window * self.input_ratio)

    def assemble(
        self,
        *,
        message: str,
        context: str,
        agent_role: str | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> ContextPackage:
        """Build a complete context package for an LLM request.

        Steps:
            1. Load P0 (mandatory) — agent prompts and policies.
            2. Search dataset for P1 (critical) — relevant files,
               excluding anything already present in P0.
            3. Append P4 (background) — recent conversation history,
               trimmed to fit the remaining budget.
            4. Format and pack into a single system prompt, respecting
               the token budget.

        Args:
            message: The user's request text.
            context: Active context scope (``"work"`` or
                ``"personal"``).
            agent_role: Active agent role (e.g. ``"secretary"``).
                When provided, only the prompt file whose stem matches
                the role is included; other role descriptions are
                omitted.  Policies are always included regardless.
            conversation_history: Optional list of prior messages for
                multi-turn conversations.  Each entry is a dict with
                ``"role"`` (``"user"`` / ``"assistant"``) and
                ``"content"`` keys.

        Returns:
            A :class:`ContextPackage` with the assembled system prompt
            and metadata about what was included.
        """
        budget = self.token_budget
        sections: list[str] = []
        tokens_used = 0

        # ── P0: agent prompt + policies (mandatory) ──────────────────
        p0_files = self._load_p0_files(context=context)
        if agent_role is not None:
            p0_files = self._filter_prompts_by_role(
                p0_files, agent_role=agent_role,
            )
        p0_text = self._format_p0(p0_files, context=context, agent_role=agent_role)
        p0_tokens = count_tokens(p0_text)
        sections.append(p0_text)
        tokens_used += p0_tokens
        logger.debug("P0 (prompt + policies): %d tokens", p0_tokens)
        etrace.detail(
            "P0 loaded",
            module="context_assembler",
            files=len(p0_files),
            tokens=p0_tokens,
        )

        # ── P1: dataset search results (critical) ────────────────────
        p0_paths = {f.relative_path for f in p0_files}
        search_results = self._search_dataset(
            message=message,
            context=context,
        )
        search_results = [
            r for r in search_results if r.file_path not in p0_paths
        ]

        included_results: list[SearchResult] = []
        if search_results:
            p1_text, included_results = self._format_search_results(
                results=search_results,
                budget_remaining=budget - tokens_used,
            )
            if p1_text:
                p1_tokens = count_tokens(p1_text)
                sections.append(p1_text)
                tokens_used += p1_tokens
                logger.debug(
                    "P1 (search results): %d tokens, %d files",
                    p1_tokens,
                    len(included_results),
                )
                etrace.detail(
                    "P1 loaded",
                    module="context_assembler",
                    results_included=len(included_results),
                    tokens=p1_tokens,
                )
                for i, r in enumerate(included_results[:5]):
                    etrace.trace_entry(
                        "Search result included",
                        module="context_assembler",
                        file_path=r.file_path,
                        score=round(r.score, 2),
                    )

        # ── P4: conversation history (background) ────────────────────
        conv_messages_included = 0
        if conversation_history:
            p4_text, conv_messages_included = self._format_conversation_history(
                history=conversation_history,
                budget_remaining=budget - tokens_used,
            )
            if p4_text:
                p4_tokens = count_tokens(p4_text)
                sections.append(p4_text)
                tokens_used += p4_tokens
                logger.debug(
                    "P4 (conversation history): %d tokens, %d messages",
                    p4_tokens,
                    conv_messages_included,
                )
                etrace.detail(
                    "P4 loaded",
                    module="context_assembler",
                    messages_included=conv_messages_included,
                    tokens=p4_tokens,
                )

        budget_remaining = budget - tokens_used
        etrace.step(
            "Context assembly complete",
            module="context_assembler",
            total_tokens=tokens_used,
            budget_remaining=budget_remaining,
        )
        etrace.detail(
            "Budget status",
            module="context_assembler",
            total_used=tokens_used,
            budget=budget,
            remaining=budget_remaining,
        )

        system_prompt = "\n\n".join(sections)
        return ContextPackage(
            system_prompt=system_prompt,
            search_results=included_results,
            p0_files=[f.relative_path for f in p0_files],
            total_tokens=tokens_used,
            budget_remaining=budget_remaining,
            conversation_messages_included=conv_messages_included,
        )

    # ── P0 helpers ────────────────────────────────────────────────────

    def _load_p0_files(self, *, context: str) -> list[DatasetFile]:
        """Load all prompt and policy files matching *context*.

        Files with ``context: global`` or a context matching the
        request scope are included.  Files with a different context
        are excluded.

        Returns:
            List of parsed :class:`DatasetFile` objects.
        """
        if self.dataset_reader is None:
            return []

        results: list[DatasetFile] = []
        for path in self.dataset_reader.list_files():
            rel = str(path.relative_to(self.dataset_reader.dataset_path))
            if not any(rel.startswith(d) for d in _P0_DIRECTORIES):
                continue
            try:
                df = self.dataset_reader.read_file(rel)
            except (FileNotFoundError, UnicodeDecodeError, OSError):
                logger.warning("Failed to read P0 file: %s", rel)
                continue
            # Context filtering: include global + matching scope.
            if df.context and df.context not in (context, "global"):
                continue
            results.append(df)

        return results

    @staticmethod
    def _filter_prompts_by_role(
        files: list[DatasetFile],
        *,
        agent_role: str,
    ) -> list[DatasetFile]:
        """Keep only the prompt file matching *agent_role*; retain all policies.

        Matching uses the file stem: ``prompts/secretary.md`` matches
        role ``"secretary"``.  If no prompt matches, all original files
        are returned unchanged so the LLM still has context.
        """
        prompts = [
            f for f in files if f.relative_path.startswith("prompts/")
        ]
        non_prompts = [
            f for f in files if not f.relative_path.startswith("prompts/")
        ]
        matching = [
            f for f in prompts
            if _prompt_file_matches_role(f.relative_path, agent_role)
        ]
        if not matching:
            logger.warning(
                "No prompt file matches agent_role=%r; "
                "including all %d prompt(s).",
                agent_role,
                len(prompts),
            )
            return files
        return matching + non_prompts

    @staticmethod
    def _format_p0(
        files: list[DatasetFile],
        *,
        context: str,
        agent_role: str | None = None,
    ) -> str:
        """Format P0 files into the opening section of the system prompt.

        Places the base identity first, then agent prompts, then
        policies — following the "beginning of context = high
        attention" principle from the TRD.

        When *agent_role* is set the identity block includes an
        explicit role binding and the section heading reads
        "Active Role" instead of "Agent Roles".
        """
        parts: list[str] = []

        # Base identity — always present regardless of data layer.
        identity = (
            f"You are Harle, a personal AI assistant. "
            f"Current context scope: {context}. "
        )
        if agent_role:
            identity += f"Your active role: {agent_role}. "
        identity += (
            f"Answer using information from the user's dataset when "
            f"available. Lead with the direct answer: put the most "
            f"relevant fact or conclusion first (e.g. a date, a yes/no, "
            f"or a one-sentence takeaway). Be concise; avoid padding "
            f"with generic sections when a short answer suffices."
        )
        parts.append(identity)

        prompts = [f for f in files if f.relative_path.startswith("prompts/")]
        policies = [f for f in files if f.relative_path.startswith("policies/")]

        if prompts:
            heading = "## Active Role" if agent_role else "## Agent Roles"
            parts.append(heading)
            for f in prompts:
                title = f.title or f.relative_path
                parts.append(f"### {title}\n\n{f.content.strip()}")

        if policies:
            parts.append("## Active Policies")
            for f in policies:
                title = f.title or f.relative_path
                parts.append(f"### {title}\n\n{f.content.strip()}")

        return "\n\n".join(parts)

    # ── P4 helpers ────────────────────────────────────────────────────

    @staticmethod
    def _format_conversation_history(
        *,
        history: list[dict[str, str]],
        budget_remaining: int,
    ) -> tuple[str, int]:
        """Format conversation messages into a context section.

        Adds messages from most recent backwards until the token budget
        is exhausted, then returns them in chronological order.

        Args:
            history: Messages with ``"role"`` and ``"content"`` keys,
                ordered oldest-first.
            budget_remaining: Maximum tokens available for this section.

        Returns:
            Tuple of ``(formatted_text, messages_included)``.
        """
        if not history:
            return "", 0

        header = "## Conversation History"
        header_tokens = count_tokens(header)
        if header_tokens >= budget_remaining:
            return "", 0

        remaining = budget_remaining - header_tokens
        selected: list[str] = []

        for msg in reversed(history):
            role_label = "User" if msg["role"] == "user" else "Assistant"
            entry = f"**{role_label}:** {msg['content']}"
            entry_tokens = count_tokens(entry)
            if entry_tokens > remaining:
                break
            selected.append(entry)
            remaining -= entry_tokens

        if not selected:
            return "", 0

        selected.reverse()
        parts = [header, *selected]
        return "\n\n".join(parts), len(selected)

    # ── P1 helpers ────────────────────────────────────────────────────

    def _search_dataset(
        self,
        *,
        message: str,
        context: str,
    ) -> list[SearchResult]:
        """Query the search engine for files relevant to *message*."""
        if self.search_engine is None:
            return []

        query = SearchQuery(
            query=message,
            context=context,
            max_results=self.max_search_results,
        )
        response = self.search_engine.search(query)
        return getattr(response, "file_results", response)

    def _format_search_results(
        self,
        *,
        results: list[SearchResult],
        budget_remaining: int,
    ) -> tuple[str, list[SearchResult]]:
        """Format search results into context text within *budget_remaining*.

        Adds results one by one.  For each result the assembler first
        tries the full file content; if that exceeds the remaining
        budget it falls back to the snippet.  Stops when the budget
        is exhausted.

        Returns:
            Tuple of ``(formatted_text, included_results)``.
        """
        if not results:
            return "", []

        header = "## Relevant Dataset Files"
        header_tokens = count_tokens(header)
        if header_tokens > budget_remaining:
            return "", []

        parts: list[str] = [header]
        tokens_used = header_tokens
        included: list[SearchResult] = []

        for result in results:
            entry = self._render_result_entry(result, full_content=True)
            entry_tokens = count_tokens(entry)

            # If full content doesn't fit, try the snippet version.
            if tokens_used + entry_tokens > budget_remaining:
                entry = self._render_result_entry(result, full_content=False)
                entry_tokens = count_tokens(entry)
                if tokens_used + entry_tokens > budget_remaining:
                    logger.debug(
                        "Budget exhausted after %d search results.",
                        len(included),
                    )
                    break

            parts.append(entry)
            included.append(result)
            tokens_used += entry_tokens

        if not included:
            return "", []

        return "\n\n".join(parts), included

    def _render_result_entry(
        self,
        result: SearchResult,
        *,
        full_content: bool,
    ) -> str:
        """Render a single search result as a Markdown section.

        Args:
            result: The search result to render.
            full_content: If ``True``, attempt to load the full file
                body from the dataset reader.  Falls back to the
                snippet when the file cannot be read.
        """
        body: str | None = None
        if full_content:
            body = self._load_search_result_body(result)
        if body is None:
            body = result.snippet or ""

        tags_line = f"Tags: {', '.join(result.tags)}" if result.tags else ""
        display_title = result.heading_path or result.title
        heading = f"### {display_title} ({result.file_path})"
        pieces = [heading]
        if tags_line:
            pieces.append(tags_line)
        pieces.append(f"\n{body.strip()}")
        if result.chunk_index is not None:
            hint_scope = f" — {result.heading_path}" if result.heading_path else ""
            pieces.append(
                f"\n\n_Excerpt from `{result.file_path}`{hint_scope}. "
                f"For the full document, read that path._"
            )
        return "\n".join(pieces)

    def _load_search_result_body(self, result: SearchResult) -> str | None:
        """Load file body or the matching chunk (deterministic re-chunk)."""
        if self.dataset_reader is None:
            return None
        try:
            df = self.dataset_reader.read_file(result.file_path)
        except (FileNotFoundError, UnicodeDecodeError, OSError):
            return None

        body = df.content or ""
        if result.chunk_index is None:
            return body

        cfg = get_chunking_config()
        token_count = count_tokens(body)
        strategy = get_strategy(
            result.file_path,
            token_count,
            chunking_enabled=cfg.enabled,
            knowledge_token_threshold=cfg.knowledge_token_threshold,
        )
        chunks = chunk_file(
            content=df.content or "",
            title=df.title,
            tags=list(df.tags or []),
            context=df.context,
            relative_path=result.file_path,
            strategy=strategy,
            contextual_enrichment=cfg.contextual_enrichment,
            paragraph_max_tokens=cfg.paragraph_max_tokens,
        )
        for c in chunks:
            if c.chunk_index == result.chunk_index:
                if cfg.contextual_enrichment and c.context_block:
                    return (c.context_block + c.content).strip()
                return c.content.strip()
        return body

    def _load_file_content(self, relative_path: str) -> str | None:
        """Load full Markdown body for a dataset file.

        Returns:
            The body text (after frontmatter), or ``None`` on failure.
        """
        if self.dataset_reader is None:
            return None
        try:
            df = self.dataset_reader.read_file(relative_path)
            return df.content
        except (FileNotFoundError, UnicodeDecodeError, OSError):
            return None
