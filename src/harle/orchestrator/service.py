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
import signal
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, TypeVar

from harle.api.models import RunRequest, RunResponse
from harle.config import PROVIDER_OPENAI, Settings
from harle.context.assembler import ContextAssembler
from harle.db.connection import Database
from harle.debug import etrace
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


@dataclass
class _RunState:
    """Mutable per-request state used for completion and failure logging."""

    run_id: str
    started_at: datetime
    message: str
    context: str
    conversation_id: str | None
    system_prompt: str | None = None
    files_used: list[str] | None = None
    tools_called: list[str] | None = None
    result_text: str | None = None
    turns_used: int | None = None


class RunTimeoutError(TimeoutError):
    """Raised when an orchestrator request exceeds the configured timeout."""


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


def _safe_error_summary(exc: Exception) -> str:
    """Build a short, safe error summary for failed run persistence."""
    message = " ".join(str(exc).split()).strip()
    summary = exc.__class__.__name__
    if message:
        summary = f"{summary}: {message}"
    if len(summary) > RESULT_SUMMARY_MAX_CHARS:
        return summary[:RESULT_SUMMARY_MAX_CHARS] + "..."
    return summary


def _timeout_summary(duration_ms: int | None) -> str:
    """Build a short timeout summary with elapsed time when available."""
    if duration_ms is None:
        return "Run timed out before completion"
    return f"Run timed out before completion (elapsed: {duration_ms} ms)"


@contextmanager
def _run_timeout(seconds: int | None) -> object:
    """Apply a per-request wall-clock timeout on Unix main-thread execution.

    Signal-based timeout only works in the main thread; in other threads
    (e.g. under TestClient) this is a no-op so tests do not raise
    "signal only works in main thread".
    """
    if not seconds or seconds <= 0:
        yield
        return

    if threading.current_thread() is not threading.main_thread():
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)

    def _handle_timeout(signum: int, frame: object | None) -> None:
        raise RunTimeoutError("Run timed out before completion")

    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


_T = TypeVar("_T")


def _run_with_timeout(seconds: int | None, thunk: Callable[[], _T]) -> _T:
    """Run a callable under a wall-clock timeout that works in any thread.

    On the main thread uses SIGALRM; on worker threads (e.g. under
    run_in_threadpool) runs the thunk in a separate thread and waits
    with timeout so the server-side limit is enforced in production.
    """
    if not seconds or seconds <= 0:
        return thunk()

    if threading.current_thread() is threading.main_thread():
        with _run_timeout(seconds):
            return thunk()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(thunk)
        try:
            return future.result(timeout=seconds)
        except FuturesTimeoutError:
            raise RunTimeoutError("Run timed out before completion")


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
    run_timeout_seconds: int | None = field(default=60)
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

        etrace.detail(
            "Agent execution started",
            module="orchestrator",
            model=self.model,
            max_turns=self.max_iterations,
            has_tools=bool(self.tool_registry),
        )

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

    def _finalize_run(
        self,
        *,
        state: _RunState,
        ended_at: datetime,
        status: str,
        error_summary: str | None = None,
        result_body: str | None = None,
        suppress_persistence_errors: bool = False,
    ) -> None:
        """Persist vault logs and run records from a single code path.

        All terminal statuses (``completed``, ``failed``, ``timeout``,
        ``aborted``) flow through this helper so ``create_run(...)``
        remains the single persistence path for run records.
        """
        duration_ms = int((ended_at - state.started_at).total_seconds() * 1000)
        result_text = result_body if result_body is not None else state.result_text
        result_summary_source = error_summary or result_text
        result_summary = (
            result_summary_source[:RESULT_SUMMARY_MAX_CHARS] + "..."
            if result_summary_source
            and len(result_summary_source) > RESULT_SUMMARY_MAX_CHARS
            else result_summary_source
        )
        result_path: str | None = None
        context_path: str | None = None
        if self.dataset_path:
            try:
                from harle.logging.run_logger import build_result_body, log_run_to_vault

                vault_result_body = build_result_body(
                    status=status,
                    result_text=state.result_text,
                    summary=result_summary,
                    duration_ms=duration_ms,
                )

                result_path, context_path = log_run_to_vault(
                    self.dataset_path,
                    run_id=state.run_id,
                    timestamp=ended_at,
                    agent=DEFAULT_AGENT_ROLE,
                    status=status,
                    context_scope=state.context,
                    result_body=vault_result_body,
                    context_body=state.system_prompt,
                    store_context=self.run_log_store_context,
                )
                if not result_path:
                    result_path = None
                if not context_path:
                    context_path = None
            except Exception:
                if not suppress_persistence_errors:
                    raise
                logger.warning(
                    "Could not write run log for run_id=%s conversation_id=%s",
                    state.run_id,
                    state.conversation_id,
                    exc_info=True,
                )

        if self.db is not None:
            try:
                from harle.db.runs import create_run

                with self.db.session() as session:
                    create_run(
                        session,
                        run_id=state.run_id,
                        timestamp=ended_at,
                        user_request=state.message,
                        context_scope=state.context,
                        agent=DEFAULT_AGENT_ROLE,
                        status=status,
                        files_used=state.files_used,
                        tools_called=state.tools_called,
                        model_used=self.model if self.use_agent_runner else None,
                        result_summary=result_summary,
                        result_path=result_path,
                        context_path=context_path,
                        conversation_id=state.conversation_id,
                        duration_ms=duration_ms,
                    )
            except Exception:
                if not suppress_persistence_errors:
                    raise
                logger.warning(
                    "Could not persist run record for run_id=%s conversation_id=%s",
                    state.run_id,
                    state.conversation_id,
                    exc_info=True,
                )

        etrace.step("Run logged", module="orchestrator")

    def _finalize_run_safely(
        self,
        **kwargs: object,
    ) -> None:
        """Best-effort wrapper for failed-run finalization."""
        try:
            self._finalize_run(
                **kwargs,
                suppress_persistence_errors=True,
            )
        except Exception as exc:  # noqa: BLE001
            state = kwargs.get("state")
            run_id = getattr(state, "run_id", None)
            conversation_id = getattr(state, "conversation_id", None)
            logger.warning(
                "Could not finalize failed run record for run_id=%s conversation_id=%s: %s",
                run_id,
                conversation_id,
                exc,
            )

    def record_aborted_request(
        self,
        *,
        request: RunRequest,
        result_body: str = "Client disconnected before response completed",
    ) -> str:
        """Persist a minimal aborted run record when the client disconnects early."""
        state = _RunState(
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            started_at=datetime.now(timezone.utc),
            message=request.message,
            context=request.context,
            conversation_id=request.conversation_id,
        )
        self._finalize_run_safely(
            state=state,
            ended_at=datetime.now(timezone.utc),
            status="aborted",
            error_summary=result_body,
            result_body=result_body,
        )
        logger.warning(
            "Recorded aborted request for run_id=%s conversation_id=%s",
            state.run_id,
            state.conversation_id,
        )
        return state.run_id

    # ── one-shot execution ────────────────────────────────────────────

    def _run_core(self, request: RunRequest, state: _RunState) -> _AgentResult:
        """Assembly + execute + state update only; caller is responsible for finalize."""
        if self.context_assembler is not None:
            package = self.context_assembler.assemble(
                message=request.message,
                context=request.context,
                agent_role=DEFAULT_AGENT_ROLE,
            )
            state.system_prompt = package.system_prompt
            state.files_used = _files_used_from_package(
                package.p0_files,
                package.search_results,
            )
            logger.info(
                "Context assembled: %d tokens, %d search results, "
                "%d P0 files, %d budget remaining",
                package.total_tokens,
                len(package.search_results),
                len(package.p0_files),
                package.budget_remaining,
            )
            etrace.step(
                "Context assembled",
                module="orchestrator",
                tokens=package.total_tokens,
                search_results=len(package.search_results),
                p0_files=len(package.p0_files),
                budget_remaining=package.budget_remaining,
            )

        agent_result = self._execute(
            user_message=request.message,
            context=request.context,
            conversation_id=state.conversation_id,
            system_prompt=state.system_prompt,
        )
        state.result_text = agent_result.text
        state.tools_called = agent_result.tools_called or None
        state.turns_used = agent_result.turns_used or None
        etrace.step(
            "Agent execution complete",
            module="orchestrator",
            tools_called=agent_result.tools_called,
            turns_used=agent_result.turns_used,
        )
        return agent_result

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
        state = _RunState(
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            started_at=datetime.now(timezone.utc),
            message=request.message,
            context=request.context,
            conversation_id=request.conversation_id,
        )
        agent_result: _AgentResult | None = None

        with etrace.span(
            "handle_request",
            level=etrace.STEP,
            module="orchestrator",
            run_id=state.run_id,
        ):
            etrace.step(
                "Routed to agent",
                module="orchestrator",
                agent=DEFAULT_AGENT_ROLE,
                routing_method="default",
            )
            try:
                agent_result = _run_with_timeout(
                    self.run_timeout_seconds,
                    lambda: self._run_core(request, state),
                )
                self._finalize_run(
                    state=state,
                    ended_at=datetime.now(timezone.utc),
                    status="completed",
                    suppress_persistence_errors=True,
                )
            except RunTimeoutError:
                duration_ms = int(
                    (datetime.now(timezone.utc) - state.started_at).total_seconds() * 1000
                )
                error_summary = _timeout_summary(duration_ms)
                logger.warning(
                    "Run timed out (run_id=%s conversation_id=%s)",
                    state.run_id,
                    state.conversation_id,
                    extra={
                        "run_id": state.run_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "user_message": state.message,
                        "context_scope": state.context,
                        "conversation_id": state.conversation_id,
                        "system_prompt": state.system_prompt,
                        "files_used": state.files_used,
                        "tools_called": state.tools_called,
                        "result_text": state.result_text,
                    },
                )
                self._finalize_run_safely(
                    state=state,
                    ended_at=datetime.now(timezone.utc),
                    status="timeout",
                    error_summary=error_summary,
                    result_body=error_summary,
                )
                raise
            except ValueError as exc:
                error_summary = _safe_error_summary(exc)
                logger.warning(
                    "Run failed with ValueError (run_id=%s conversation_id=%s): %s",
                    state.run_id,
                    state.conversation_id,
                    error_summary,
                )
                self._finalize_run_safely(
                    state=state,
                    ended_at=datetime.now(timezone.utc),
                    status="failed",
                    error_summary=error_summary,
                    result_body=error_summary,
                )
                raise
            except Exception as exc:
                error_summary = _safe_error_summary(exc)
                logger.warning(
                    "Run failed (run_id=%s conversation_id=%s): %s",
                    state.run_id,
                    state.conversation_id,
                    error_summary,
                )
                self._finalize_run_safely(
                    state=state,
                    ended_at=datetime.now(timezone.utc),
                    status="failed",
                    error_summary=error_summary,
                    result_body=error_summary,
                )
                raise

            if agent_result and agent_result.tools_called:
                logger.info(
                    "Run %s used %d turn(s), tools: %s",
                    state.run_id, agent_result.turns_used, agent_result.tools_called,
                )

        return RunResponse(
            run_id=state.run_id,
            status="completed",
            result=state.result_text or "",
            context=request.context,
            agent=DEFAULT_AGENT_ROLE,
            conversation_id=state.conversation_id,
            tools_called=state.tools_called,
            turns_used=state.turns_used,
        )

    # ── multi-turn chat ───────────────────────────────────────────────

    def _chat_core(self, request: RunRequest, state: _RunState) -> _AgentResult:
        """Load/create conversation, assembly, execute, persist messages; no finalize."""
        from harle.db.conversations import (
            add_message,
            create_conversation,
            get_conversation,
            get_recent_messages,
            touch_conversation,
        )

        conversation_history: list[dict[str, str]] | None = None
        if state.conversation_id is not None:
            with self.db.session() as session:
                conv = get_conversation(session, state.conversation_id)
            if conv is None:
                raise ValueError(
                    f"Conversation {state.conversation_id!r} not found."
                )
            with self.db.session() as session:
                messages = get_recent_messages(
                    session,
                    state.conversation_id,
                )
                conversation_history = [
                    {"role": m.role, "content": m.content}
                    for m in messages
                ]
        else:
            state.conversation_id = f"conv_{uuid.uuid4().hex[:12]}"
            with self.db.session() as session:
                create_conversation(
                    session,
                    conversation_id=state.conversation_id,
                    context_scope=request.context,
                    agent_role=DEFAULT_AGENT_ROLE,
                )

        if self.context_assembler is not None:
            package = self.context_assembler.assemble(
                message=request.message,
                context=request.context,
                agent_role=DEFAULT_AGENT_ROLE,
                conversation_history=conversation_history,
            )
            state.system_prompt = package.system_prompt
            state.files_used = _files_used_from_package(
                package.p0_files,
                package.search_results,
            )
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
            etrace.step(
                "Context assembled",
                module="orchestrator",
                tokens=package.total_tokens,
                search_results=len(package.search_results),
                conversation_messages=package.conversation_messages_included,
            )

        agent_result = self._execute(
            user_message=request.message,
            context=request.context,
            conversation_id=state.conversation_id,
            system_prompt=state.system_prompt,
        )
        state.result_text = agent_result.text
        state.tools_called = agent_result.tools_called or None
        state.turns_used = agent_result.turns_used or None
        etrace.step(
            "Agent execution complete",
            module="orchestrator",
            tools_called=agent_result.tools_called,
            turns_used=agent_result.turns_used,
        )

        with self.db.session() as session:
            add_message(
                session,
                conversation_id=state.conversation_id,
                role="user",
                content=request.message,
                run_id=state.run_id,
            )
            add_message(
                session,
                conversation_id=state.conversation_id,
                role="assistant",
                content=state.result_text,
                run_id=state.run_id,
            )
            touch_conversation(session, state.conversation_id)

        return agent_result

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

        state = _RunState(
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            started_at=datetime.now(timezone.utc),
            message=request.message,
            context=request.context,
            conversation_id=request.conversation_id,
        )
        agent_result: _AgentResult | None = None

        with etrace.span(
            "handle_chat",
            level=etrace.STEP,
            module="orchestrator",
            run_id=state.run_id,
        ):
            etrace.step(
                "Routed to agent",
                module="orchestrator",
                agent=DEFAULT_AGENT_ROLE,
                routing_method="default",
            )
            try:
                agent_result = _run_with_timeout(
                    self.run_timeout_seconds,
                    lambda: self._chat_core(request, state),
                )
                self._finalize_run(
                    state=state,
                    ended_at=datetime.now(timezone.utc),
                    status="completed",
                    suppress_persistence_errors=True,
                )
            except RunTimeoutError:
                duration_ms = int(
                    (datetime.now(timezone.utc) - state.started_at).total_seconds() * 1000
                )
                error_summary = _timeout_summary(duration_ms)
                logger.warning(
                    "Chat run timed out (run_id=%s conversation_id=%s)",
                    state.run_id,
                    state.conversation_id,
                    extra={
                        "run_id": state.run_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "user_message": state.message,
                        "context_scope": state.context,
                        "conversation_id": state.conversation_id,
                        "system_prompt": state.system_prompt,
                        "files_used": state.files_used,
                        "tools_called": state.tools_called,
                        "result_text": state.result_text,
                    },
                )
                self._finalize_run_safely(
                    state=state,
                    ended_at=datetime.now(timezone.utc),
                    status="timeout",
                    error_summary=error_summary,
                    result_body=error_summary,
                )
                raise
            except ValueError as exc:
                error_summary = _safe_error_summary(exc)
                logger.warning(
                    "Chat run failed with ValueError (run_id=%s conversation_id=%s): %s",
                    state.run_id,
                    state.conversation_id,
                    error_summary,
                )
                self._finalize_run_safely(
                    state=state,
                    ended_at=datetime.now(timezone.utc),
                    status="failed",
                    error_summary=error_summary,
                    result_body=error_summary,
                )
                raise
            except Exception as exc:
                error_summary = _safe_error_summary(exc)
                logger.warning(
                    "Chat run failed (run_id=%s conversation_id=%s): %s",
                    state.run_id,
                    state.conversation_id,
                    error_summary,
                )
                self._finalize_run_safely(
                    state=state,
                    ended_at=datetime.now(timezone.utc),
                    status="failed",
                    error_summary=error_summary,
                    result_body=error_summary,
                )
                raise

            if agent_result and agent_result.tools_called:
                logger.info(
                    "Chat run %s used %d turn(s), tools: %s",
                    state.run_id, agent_result.turns_used, agent_result.tools_called,
                )

        return RunResponse(
            run_id=state.run_id,
            status="completed",
            result=state.result_text or "",
            context=request.context,
            agent=DEFAULT_AGENT_ROLE,
            conversation_id=state.conversation_id,
            tools_called=state.tools_called,
            turns_used=state.turns_used,
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
            run_timeout_seconds=settings.HARLE_RUN_TIMEOUT_SECONDS,
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
        run_timeout_seconds=settings.HARLE_RUN_TIMEOUT_SECONDS,
        use_agent_runner=False,
    )
