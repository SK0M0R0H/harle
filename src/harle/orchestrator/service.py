"""Request orchestrator for Harle.

Coordinates context assembly, conversation management, and LLM
generation.  Supports two execution paths:

1. **Agent Runner** (Level 1+): Uses the OpenAI Agents SDK ``Runner``
   for multi-step reasoning with tool calls.  Enabled when an OpenAI
   API key is available.

2. **Legacy provider** (fallback): Single LLM call via the
   ``LLMProvider`` protocol.  Used when no API key is set (echo
   provider).

When a :class:`ToolRegistry` is provided, the agent receives
SDK-compatible tool functions and can call them during reasoning.
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
from harle.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

DEFAULT_AGENT_ROLE: str = "researcher"
RESULT_SUMMARY_MAX_CHARS: int = 2000

_TOOL_THINKING_INSTRUCTION: str = (
    "\n\nBefore calling any tool, briefly state what you know so far, "
    "what you still need, and why you are calling this specific tool. "
    "This helps maintain reasoning coherence across multiple steps."
)


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


# ── Agent execution result ────────────────────────────────────────────


@dataclass(frozen=True)
class _AgentResult:
    """Internal result from either the Runner or the legacy provider."""

    text: str
    tools_called: list[str] = field(default_factory=list)
    turns_used: int = 0


def _extract_run_metadata(result: object) -> tuple[list[str], int]:
    """Extract tool names and turn count from an Agents SDK RunResult.

    Uses duck typing so the orchestrator does not import SDK item
    types directly.
    """
    tools: list[str] = []
    turns = 0
    for item in getattr(result, "new_items", []):
        item_type = getattr(item, "type", "")
        if item_type == "tool_call_item":
            raw = getattr(item, "raw_item", None)
            name = getattr(raw, "name", None)
            if name and name not in tools:
                tools.append(name)
        elif item_type == "message_output_item":
            turns += 1
    turns = max(turns, len(getattr(result, "raw_responses", [])))
    return tools, turns


# ── Orchestrator ──────────────────────────────────────────────────────


@dataclass
class OrchestratorService:
    """Orchestrator that assembles context and routes requests to an LLM.

    Attributes:
        llm_provider: The LLM generation backend (fallback path).
        context_assembler: Optional assembler for dataset-aware
            context packing.
        db: Optional database connection for conversation and runs.
        dataset_path: Optional vault root path for writing run logs.
        run_log_store_context: Whether to store assembled context in
            logs.
        tool_registry: Optional tool registry providing agent tools.
        model: LLM model name for the Agents SDK Agent.
        max_iterations: Maximum turns for the agentic loop.
        use_agent_runner: When ``True``, use the Agents SDK Runner
            instead of the direct LLM provider.
    """

    llm_provider: LLMProvider
    context_assembler: ContextAssembler | None = field(default=None)
    db: Database | None = field(default=None)
    dataset_path: str | None = field(default=None)
    run_log_store_context: bool = field(default=False)
    tool_registry: ToolRegistry | None = field(default=None)
    model: str = field(default="gpt-4o-mini")
    max_iterations: int = field(default=10)
    use_agent_runner: bool = field(default=False)

    # ── execution backends ────────────────────────────────────────────

    def _build_instructions(self, system_prompt: str | None, has_tools: bool) -> str:
        """Build agent instructions from the system prompt and tool metadata.

        When tools are available, appends thinking instructions and
        tool skills to encourage coherent multi-step reasoning.
        """
        base = system_prompt or (
            "You are Harle, a concise assistant. "
            "Answer directly and keep structure clear."
        )

        if not has_tools or self.tool_registry is None:
            return base

        parts = [base]

        all_tool_names = self.tool_registry.list_all_tools()
        skills = self.tool_registry.get_skills_for_tools(all_tool_names)
        if skills:
            skill_sections = [
                f"## Tool Skill: {s.name}\n\n{s.content}" for s in skills
            ]
            parts.append("\n\n".join(skill_sections))

        parts.append(_TOOL_THINKING_INSTRUCTION)
        return "\n\n".join(parts)

    def _execute_with_runner(
        self,
        *,
        user_message: str,
        system_prompt: str | None,
    ) -> _AgentResult:
        """Execute via the Agents SDK Runner with optional tool support.

        Creates an Agent with instructions and tools, then runs the
        agentic loop.  If ``MaxTurnsExceeded`` is raised the partial
        result is returned with a note.
        """
        from agents import Agent, MaxTurnsExceeded, Runner

        tools = []
        if self.tool_registry:
            all_tool_names = self.tool_registry.list_all_tools()
            tools = self.tool_registry.get_agent_tools(all_tool_names)

        instructions = self._build_instructions(system_prompt, bool(tools))

        agent = Agent(
            name=DEFAULT_AGENT_ROLE,
            instructions=instructions,
            tools=tools,
            model=self.model,
        )

        try:
            result = Runner.run_sync(
                agent, user_message, max_turns=self.max_iterations,
            )
            tools_called, turns_used = _extract_run_metadata(result)
            return _AgentResult(
                text=result.final_output,
                tools_called=tools_called,
                turns_used=turns_used,
            )
        except MaxTurnsExceeded:
            logger.warning(
                "Agent exceeded max_turns=%d for message: %.80s",
                self.max_iterations, user_message,
            )
            return _AgentResult(
                text=(
                    "I used all available reasoning steps but could not "
                    "finish.  Please try a more specific request or "
                    "increase the iteration limit."
                ),
                turns_used=self.max_iterations,
            )

    def _execute_with_provider(
        self,
        *,
        user_message: str,
        context: str,
        conversation_id: str | None,
        system_prompt: str | None,
    ) -> _AgentResult:
        """Execute via the legacy LLM provider (single call, no tools)."""
        text = self.llm_provider.generate(
            prompt=user_message,
            context=context,
            conversation_id=conversation_id,
            system_prompt=system_prompt,
        )
        return _AgentResult(text=text)

    def _execute(
        self,
        *,
        user_message: str,
        context: str,
        conversation_id: str | None,
        system_prompt: str | None,
    ) -> _AgentResult:
        """Route execution to the Runner or the legacy provider."""
        if self.use_agent_runner:
            return self._execute_with_runner(
                user_message=user_message,
                system_prompt=system_prompt,
            )
        return self._execute_with_provider(
            user_message=user_message,
            context=context,
            conversation_id=conversation_id,
            system_prompt=system_prompt,
        )

    # ── one-shot execution ────────────────────────────────────────────

    def run(self, *, request: RunRequest) -> RunResponse:
        """Process a run request end-to-end.

        Steps:
            1. If a context assembler is available, build a
               :class:`ContextPackage`.
            2. Execute via the Runner or legacy provider.
            3. Log the run to the vault and (if db is set) the
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
                agent_role=DEFAULT_AGENT_ROLE,
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

        agent_result = self._execute(
            user_message=request.message,
            context=request.context,
            conversation_id=request.conversation_id,
            system_prompt=system_prompt,
        )
        result_text = agent_result.text

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
                        tools_called=agent_result.tools_called or None,
                        model_used=self.model if self.use_agent_runner else None,
                        result_summary=result_summary,
                        result_path=result_path,
                        context_path=context_path,
                        conversation_id=request.conversation_id,
                        duration_ms=duration_ms,
                    )
            except Exception as e:
                logger.warning("Could not persist run record: %s", e)

        if agent_result.tools_called:
            logger.info(
                "Run %s used %d turn(s), tools: %s",
                run_id, agent_result.turns_used, agent_result.tools_called,
            )

        return RunResponse(
            run_id=run_id,
            status="completed",
            result=result_text,
            context=request.context,
            conversation_id=request.conversation_id,
            tools_called=agent_result.tools_called or None,
            turns_used=agent_result.turns_used or None,
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
                agent_role=DEFAULT_AGENT_ROLE,
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

        # ── execution ────────────────────────────────────────────────
        agent_result = self._execute(
            user_message=request.message,
            context=request.context,
            conversation_id=conv_id,
            system_prompt=system_prompt,
        )
        result_text = agent_result.text

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

        # ── persist run ──────────────────────────────────────────────
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
                    tools_called=agent_result.tools_called or None,
                    model_used=self.model if self.use_agent_runner else None,
                    result_summary=result_summary,
                    result_path=result_path_v,
                    context_path=context_path_v,
                    conversation_id=conv_id,
                    duration_ms=duration_ms,
                )
        except Exception as e:
            logger.warning("Could not persist run record: %s", e)
            try:
                with self.db.session() as session:
                    session.rollback()
            except Exception:  # noqa: S110
                pass

        if agent_result.tools_called:
            logger.info(
                "Chat run %s used %d turn(s), tools: %s",
                run_id, agent_result.turns_used, agent_result.tools_called,
            )

        return RunResponse(
            run_id=run_id,
            status="completed",
            result=result_text,
            context=request.context,
            conversation_id=conv_id,
            tools_called=agent_result.tools_called or None,
            turns_used=agent_result.turns_used or None,
        )


def build_orchestrator(
    *,
    settings: Settings,
    context_assembler: ContextAssembler | None = None,
    db: Database | None = None,
    tool_registry: ToolRegistry | None = None,
) -> OrchestratorService:
    """Build a runtime orchestrator with provider fallback.

    When an OpenAI API key is available the orchestrator uses the
    Agents SDK Runner for multi-step reasoning.  Otherwise it falls
    back to the echo provider for local development.

    Args:
        settings: Application settings (LLM provider, model, etc.).
        context_assembler: Optional context assembler.
        db: Optional database connection.
        tool_registry: Optional tool registry with registered modules.

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
            tool_registry=tool_registry,
            model=settings.HARLE_LLM_MODEL,
            max_iterations=settings.HARLE_MAX_ITERATIONS,
            use_agent_runner=True,
        )

    provider = EchoProvider()
    return OrchestratorService(
        llm_provider=provider,
        context_assembler=context_assembler,
        db=db,
        dataset_path=settings.HARLE_DATASET_PATH,
        run_log_store_context=settings.HARLE_RUN_LOG_STORE_CONTEXT,
        tool_registry=tool_registry,
        model=settings.HARLE_LLM_MODEL,
        max_iterations=settings.HARLE_MAX_ITERATIONS,
        use_agent_runner=False,
    )
