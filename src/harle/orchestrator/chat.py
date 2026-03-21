"""Chat pipeline: conversation lifecycle, context assembly, response."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from harle.api.models import RunRequest, RunResponse
from harle.debug import etrace

from harle.orchestrator.router import route as route_message
from harle.orchestrator.router import route_with_pinned_role
from harle.orchestrator.state import (
    DEFAULT_AGENT_ROLE,
    AgentResult,
    RunState,
    RunTimeoutError,
    files_used_from_package,
)
from harle.orchestrator.timeout import (
    run_with_timeout,
    safe_error_summary,
    timeout_summary,
)

logger = logging.getLogger(__name__)


def _handoffs_to_api(
    handoffs: list | None,
) -> list[dict[str, str]] | None:
    """Serialize handoff records for API responses."""
    if not handoffs:
        return None
    return [
        {
            "source_agent": h.source_agent,
            "target_agent": h.target_agent,
            "reason": h.reason,
        }
        for h in handoffs
    ]


class ChatMixin:
    """``_chat_core``, ``chat``, ``record_aborted_request``."""

    def record_aborted_request(
        self,
        *,
        request: RunRequest,
        result_body: str = "Client disconnected before response completed",
    ) -> str:
        """Persist a minimal aborted run record when the client disconnects early."""
        state = RunState(
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

    def _chat_core(self, request: RunRequest, state: RunState) -> AgentResult:
        """Load/create conversation, assembly, execute, persist messages; no finalize."""
        from harle.db.conversations import (
            add_message,
            create_conversation,
            get_conversation,
            get_recent_messages,
            touch_conversation,
            update_conversation_agent_role,
        )

        conversation_history: list[dict[str, str]] | None = None
        if state.conversation_id is not None:
            with self.db.session() as session:
                conv = get_conversation(session, state.conversation_id)
                if conv is None:
                    raise ValueError(
                        f"Conversation {state.conversation_id!r} not found."
                    )
                # Read attributes while the session is active (ORM instance expires on exit).
                pinned_role = conv.agent_role
            route = route_with_pinned_role(request.message, pinned_role)
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
            route = route_message(request.message)
            state.conversation_id = f"conv_{uuid.uuid4().hex[:12]}"
            with self.db.session() as session:
                create_conversation(
                    session,
                    conversation_id=state.conversation_id,
                    context_scope=request.context,
                    agent_role=route.agent_role,
                )

        state.starting_role = route.agent_role
        routed_message = route.original_message

        etrace.step(
            "Routed to agent",
            module="orchestrator",
            agent=route.agent_role,
            routing_method=route.routing_method,
        )

        if self.context_assembler is not None:
            package = self.context_assembler.assemble(
                message=routed_message,
                context=request.context,
                agent_role=route.agent_role,
                conversation_history=conversation_history,
            )
            state.system_prompt = package.system_prompt
            state.files_used = files_used_from_package(
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
            user_message=routed_message,
            context=request.context,
            conversation_id=state.conversation_id,
            system_prompt=state.system_prompt,
            agent_role=route.agent_role,
            routing_method_from_router=route.routing_method,
        )
        state.result_text = agent_result.text
        state.tools_called = agent_result.tools_called or None
        state.turns_used = agent_result.turns_used or None
        state.plan_text = agent_result.plan_text
        state.plan_revisions = agent_result.plan_revisions
        state.planning_tool_context = agent_result.planning_tool_context
        state.routing_method = agent_result.routing_method
        state.reflection_triggered = agent_result.reflection_triggered
        state.reflection_improved = agent_result.reflection_improved
        state.reflection_record = agent_result.reflection_record
        state.handoffs = agent_result.handoffs
        state.final_agent = agent_result.final_agent
        etrace.step(
            "Agent execution complete",
            module="orchestrator",
            tools_called=agent_result.tools_called,
            turns_used=agent_result.turns_used,
            routing_method=state.routing_method,
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
            if route.routing_method == "explicit_override":
                update_conversation_agent_role(
                    session,
                    state.conversation_id,
                    route.agent_role,
                )

        return agent_result

    def chat(self, *, request: RunRequest) -> RunResponse:
        """Process a user message: create or continue a conversation."""
        if self.db is None:
            raise RuntimeError(
                "Database is required for the chat pipeline. "
                "Set DATABASE_URL in the configuration."
            )

        state = RunState(
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            started_at=datetime.now(timezone.utc),
            message=request.message,
            context=request.context,
            conversation_id=request.conversation_id,
        )
        agent_result: AgentResult | None = None

        with etrace.span(
            "handle_chat",
            level=etrace.STEP,
            module="orchestrator",
            run_id=state.run_id,
        ):
            try:
                agent_result = run_with_timeout(
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
                error_summary = timeout_summary(duration_ms)
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
                error_summary = safe_error_summary(exc)
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
                error_summary = safe_error_summary(exc)
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

        response_agent = (
            state.final_agent
            or state.starting_role
            or DEFAULT_AGENT_ROLE
        )
        return RunResponse(
            run_id=state.run_id,
            status="completed",
            result=state.result_text or "",
            context=request.context,
            agent=response_agent,
            conversation_id=state.conversation_id,
            tools_called=state.tools_called,
            turns_used=state.turns_used,
            reflection_triggered=state.reflection_triggered,
            reflection_improved=state.reflection_improved,
            handoffs=_handoffs_to_api(state.handoffs),
        )
