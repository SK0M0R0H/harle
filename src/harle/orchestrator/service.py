"""Request orchestrator for Harle.

Coordinates context assembly, conversation management, and LLM
generation.  When a :class:`ContextAssembler` is available the
orchestrator searches the user's dataset and packs relevant context
before calling the LLM provider.  When a :class:`Database` is
available the orchestrator manages multi-turn conversations via the
``conversations`` CRUD layer.

Without these optional dependencies the orchestrator falls back to
direct LLM calls (prototype behaviour).
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from harle.api.models import RunRequest, RunResponse
from harle.config import PROVIDER_OPENAI, Settings
from harle.context.assembler import ContextAssembler
from harle.db.connection import Database
from harle.llm.providers import EchoProvider, LLMProvider, OpenAIProvider

logger = logging.getLogger(__name__)

DEFAULT_AGENT_ROLE: str = "secretary"
RESULT_SUMMARY_MAX_CHARS: int = 2000


def _files_used_from_package(
    p0_files: list[str],
    search_results: list,
) -> list[str]:
    """Build combined list of dataset file paths used in context (P0 + P1)."""
    paths = list(p0_files)
    for r in search_results:
        path = getattr(r, "file_path", None)
        if path and path not in paths:
            paths.append(path)
    return paths


@dataclass
class OrchestratorService:
    """Orchestrator that assembles context and routes requests to an LLM.

    When *context_assembler* is provided the :meth:`run` method will:
    1. Assemble a context package (prompts, policies, search results).
    2. Pass the assembled system prompt to the LLM provider.

    When *db* is provided the :meth:`chat` method additionally manages
    multi-turn conversations: creating or loading a conversation,
    fetching recent history for context assembly, and persisting both
    user and assistant messages.

    When *dataset_path* is set, run and chat log each execution to the
    vault ``logs/`` directory and (when *db* is set) to the ``runs``
    table.

    Without optional dependencies the provider receives only the raw
    user message (backward-compatible prototype mode).

    Attributes:
        llm_provider: The LLM generation backend.
        context_assembler: Optional assembler for dataset-aware
            context packing.
        db: Optional database connection for conversation and runs.
        dataset_path: Optional vault root path for writing run logs.
        run_log_store_context: Whether to store assembled context in logs.
    """

    llm_provider: LLMProvider
    context_assembler: ContextAssembler | None = field(default=None)
    db: Database | None = field(default=None)
    dataset_path: str | None = field(default=None)
    run_log_store_context: bool = field(default=False)

    # ── one-shot execution ────────────────────────────────────────────

    def run(self, *, request: RunRequest) -> RunResponse:
        """Process a run request end-to-end.

        Steps:
            1. If a context assembler is available, build a
               :class:`ContextPackage` with prompts, policies, and
               dataset search results.
            2. Call the LLM provider with the assembled system prompt
               (or fall back to the provider's default).
            3. Log the run to the vault logs/ and (if db is set) to the
               ``runs`` table.
            4. Return the response.

        Args:
            request: Incoming run request from the API.

        Returns:
            A :class:`RunResponse` with the generated result.
        """
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        started_at = datetime.now(timezone.utc)

        system_prompt: str | None = None
        package = None
        if self.context_assembler is not None:
            package = self.context_assembler.assemble(
                message=request.message,
                context=request.context,
            )
            system_prompt = package.system_prompt
            logger.info(
                "Context assembled: %d tokens, %d search results, "
                "%d P0 files, %d budget remaining",
                package.total_tokens,
                len(package.search_results),
                len(package.p0_files),
                package.budget_remaining,
            )

        result_text = self.llm_provider.generate(
            prompt=request.message,
            context=request.context,
            conversation_id=request.conversation_id,
            system_prompt=system_prompt,
        )

        ended_at = datetime.now(timezone.utc)
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)
        result_summary = (
            result_text[:RESULT_SUMMARY_MAX_CHARS] + "..."
            if len(result_text) > RESULT_SUMMARY_MAX_CHARS
            else result_text
        ) if result_text else None
        files_used = (
            _files_used_from_package(package.p0_files, package.search_results)
            if package
            else None
        )
        result_path: str | None = None
        context_path: str | None = None
        if self.dataset_path:
            from harle.logging.run_logger import log_run_to_vault
            result_path, context_path = log_run_to_vault(
                self.dataset_path,
                run_id=run_id,
                timestamp=ended_at,
                agent=DEFAULT_AGENT_ROLE,
                status="completed",
                context_scope=request.context,
                result_body=result_text,
                context_body=system_prompt,
                store_context=self.run_log_store_context,
            )
            if not result_path:
                result_path = None

        if self.db is not None:
            try:
                from harle.db.runs import create_run
                with self.db.session() as session:
                    create_run(
                        session,
                        run_id=run_id,
                        timestamp=ended_at,
                        user_request=request.message,
                        context_scope=request.context,
                        agent=DEFAULT_AGENT_ROLE,
                        status="completed",
                        files_used=files_used,
                        result_summary=result_summary,
                        result_path=result_path,
                        context_path=context_path,
                        conversation_id=request.conversation_id,
                        duration_ms=duration_ms,
                    )
            except Exception as e:  # e.g. no such table: runs (SQLite test db)
                logger.warning("Could not persist run record: %s", e)

        return RunResponse(
            run_id=run_id,
            status="completed",
            result=result_text,
            context=request.context,
            conversation_id=request.conversation_id,
        )

    # ── multi-turn chat ───────────────────────────────────────────────

    def chat(self, *, request: RunRequest) -> RunResponse:
        """Process a chat message with full conversation management.

        Unlike :meth:`run`, this method persists every exchange into
        the ``conversations`` / ``messages`` tables and feeds recent
        conversation history into the context assembler (P4 tier).

        When *conversation_id* is ``None`` a new conversation is
        created and its ID returned in the response.

        Requires a database connection (``self.db``).

        Args:
            request: Incoming chat request from the API.

        Returns:
            A :class:`RunResponse` including the ``conversation_id``.

        Raises:
            RuntimeError: If the database is not configured.
            ValueError: If the given *conversation_id* does not exist.
        """
        if self.db is None:
            raise RuntimeError(
                "Database is required for chat mode. "
                "Set DATABASE_URL in the configuration."
            )

        from harle.db.conversations import (
            add_message,
            create_conversation,
            get_conversation,
            get_recent_messages,
            touch_conversation,
        )

        run_id = f"run_{uuid.uuid4().hex[:12]}"
        conv_id = request.conversation_id
        started_at = datetime.now(timezone.utc)

        # ── load or create conversation ──────────────────────────────
        conversation_history: list[dict[str, str]] | None = None

        if conv_id is not None:
            with self.db.session() as session:
                conv = get_conversation(session, conv_id)
            if conv is None:
                raise ValueError(
                    f"Conversation {conv_id!r} not found."
                )
            with self.db.session() as session:
                messages = get_recent_messages(session, conv_id)
                conversation_history = [
                    {"role": m.role, "content": m.content}
                    for m in messages
                ]
        else:
            conv_id = f"conv_{uuid.uuid4().hex[:12]}"
            with self.db.session() as session:
                create_conversation(
                    session,
                    conversation_id=conv_id,
                    context_scope=request.context,
                    agent_role=DEFAULT_AGENT_ROLE,
                )

        # ── context assembly ─────────────────────────────────────────
        system_prompt: str | None = None
        package = None
        if self.context_assembler is not None:
            package = self.context_assembler.assemble(
                message=request.message,
                context=request.context,
                conversation_history=conversation_history,
            )
            system_prompt = package.system_prompt
            logger.info(
                "Context assembled: %d tokens, %d search results, "
                "%d P0 files, %d conversation messages, "
                "%d budget remaining",
                package.total_tokens,
                len(package.search_results),
                len(package.p0_files),
                package.conversation_messages_included,
                package.budget_remaining,
            )

        # ── LLM generation ───────────────────────────────────────────
        result_text = self.llm_provider.generate(
            prompt=request.message,
            context=request.context,
            conversation_id=conv_id,
            system_prompt=system_prompt,
        )

        ended_at = datetime.now(timezone.utc)
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)
        result_summary = (
            result_text[:RESULT_SUMMARY_MAX_CHARS] + "..."
            if len(result_text) > RESULT_SUMMARY_MAX_CHARS
            else result_text
        ) if result_text else None
        files_used = (
            _files_used_from_package(package.p0_files, package.search_results)
            if package
            else None
        )
        result_path_v: str | None = None
        context_path_v: str | None = None
        if self.dataset_path:
            from harle.logging.run_logger import log_run_to_vault
            rp, cp = log_run_to_vault(
                self.dataset_path,
                run_id=run_id,
                timestamp=ended_at,
                agent=DEFAULT_AGENT_ROLE,
                status="completed",
                context_scope=request.context,
                result_body=result_text,
                context_body=system_prompt,
                store_context=self.run_log_store_context,
            )
            if rp:
                result_path_v = rp
            if cp:
                context_path_v = cp

        # ── persist messages ────────────────────────────────────────
        with self.db.session() as session:
            add_message(
                session,
                conversation_id=conv_id,
                role="user",
                content=request.message,
                run_id=run_id,
            )
            add_message(
                session,
                conversation_id=conv_id,
                role="assistant",
                content=result_text,
                run_id=run_id,
            )
            touch_conversation(session, conv_id)

        # ── persist run (separate session so message commit is not affected)
        try:
            from harle.db.runs import create_run
            with self.db.session() as session:
                create_run(
                    session,
                    run_id=run_id,
                    timestamp=ended_at,
                    user_request=request.message,
                    context_scope=request.context,
                    agent=DEFAULT_AGENT_ROLE,
                    status="completed",
                    files_used=files_used,
                    result_summary=result_summary,
                    result_path=result_path_v,
                    context_path=context_path_v,
                    conversation_id=conv_id,
                    duration_ms=duration_ms,
                )
        except Exception as e:  # e.g. no such table: runs (SQLite test db)
            logger.warning("Could not persist run record: %s", e)
            try:
                with self.db.session() as session:
                    session.rollback()
            except Exception:  # noqa: S110
                pass

        return RunResponse(
            run_id=run_id,
            status="completed",
            result=result_text,
            context=request.context,
            conversation_id=conv_id,
        )


def build_orchestrator(
    *,
    settings: Settings,
    context_assembler: ContextAssembler | None = None,
    db: Database | None = None,
) -> OrchestratorService:
    """Build a runtime orchestrator with provider fallback.

    Args:
        settings: Application settings (LLM provider, model, etc.).
        context_assembler: Optional context assembler.  When provided
            the orchestrator searches the dataset and packs context
            before each LLM call.
        db: Optional database connection.  When provided the
            orchestrator can persist multi-turn conversations.

    Returns:
        A fully configured :class:`OrchestratorService`.
    """
    provider_name = settings.HARLE_LLM_PROVIDER.lower()
    openai_api_key = os.getenv("OPENAI_API_KEY")

    if provider_name == PROVIDER_OPENAI and openai_api_key:
        provider: LLMProvider = OpenAIProvider(
            model=settings.HARLE_LLM_MODEL,
            api_key=openai_api_key,
        )
        return OrchestratorService(
            llm_provider=provider,
            context_assembler=context_assembler,
            db=db,
            dataset_path=settings.HARLE_DATASET_PATH,
            run_log_store_context=settings.HARLE_RUN_LOG_STORE_CONTEXT,
        )

    provider = EchoProvider()
    return OrchestratorService(
        llm_provider=provider,
        context_assembler=context_assembler,
        db=db,
        dataset_path=settings.HARLE_DATASET_PATH,
        run_log_store_context=settings.HARLE_RUN_LOG_STORE_CONTEXT,
    )

