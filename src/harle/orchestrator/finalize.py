"""Persist vault run logs and DB run rows (single code path)."""

from __future__ import annotations

import logging
from datetime import datetime

from harle.db.connection import Database
from harle.debug import etrace

from harle.orchestrator.state import DEFAULT_AGENT_ROLE, RESULT_SUMMARY_MAX_CHARS, RunState

logger = logging.getLogger(__name__)


def finalize_orchestrator_run(
    *,
    state: RunState,
    ended_at: datetime,
    status: str,
    dataset_path: str | None,
    run_log_store_context: bool,
    db: Database | None,
    model: str,
    use_agent_runner: bool,
    reflection_min_tool_calls: int,
    error_summary: str | None = None,
    result_body: str | None = None,
    suppress_persistence_errors: bool = False,
) -> None:
    """Write vault logs and ``runs`` row for a terminal status.

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

    agent_label = (
        state.final_agent
        or state.starting_role
        or DEFAULT_AGENT_ROLE
    )
    handoffs_payload: list[dict[str, str]] | None = None
    if state.handoffs:
        handoffs_payload = [
            {
                "source_agent": h.source_agent,
                "target_agent": h.target_agent,
                "reason": h.reason,
            }
            for h in state.handoffs
        ]

    if dataset_path:
        try:
            from harle.logging.run_logger import build_result_body, log_run_to_vault
            from harle.orchestrator.planner import format_plan_for_vault
            from harle.orchestrator.reflection import format_reflection_for_vault

            vault_result_body = build_result_body(
                status=status,
                result_text=state.result_text,
                summary=result_summary,
                duration_ms=duration_ms,
            )
            plan_extra = format_plan_for_vault(
                state.plan_text,
                state.plan_revisions,
                state.planning_tool_context,
            )
            if plan_extra.strip():
                vault_result_body = (
                    f"{vault_result_body}\n\n## Plan\n\n{plan_extra}"
                    if vault_result_body
                    else f"## Plan\n\n{plan_extra}"
                )

            if state.reflection_triggered and state.reflection_record:
                refl_extra = format_reflection_for_vault(
                    triggered=True,
                    record=state.reflection_record,
                    min_tool_calls=reflection_min_tool_calls,
                )
                if refl_extra.strip():
                    vault_result_body = (
                        f"{vault_result_body}\n\n## Reflection\n\n{refl_extra}"
                        if vault_result_body
                        else f"## Reflection\n\n{refl_extra}"
                    )

            if state.models_used:
                mu_lines = "\n".join(
                    f"- **{phase}:** `{name}`"
                    for phase, name in sorted(state.models_used.items())
                )
                models_md = f"## Models Used\n\n{mu_lines}\n"
                vault_result_body = (
                    f"{vault_result_body}\n\n{models_md}"
                    if vault_result_body
                    else models_md
                )

            result_path, context_path = log_run_to_vault(
                dataset_path,
                run_id=state.run_id,
                timestamp=ended_at,
                agent=agent_label,
                status=status,
                context_scope=state.context,
                result_body=vault_result_body,
                context_body=state.system_prompt,
                store_context=run_log_store_context,
                handoffs=handoffs_payload,
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

    if db is not None:
        try:
            from harle.db.runs import create_run

            with db.session() as session:
                create_run(
                    session,
                    run_id=state.run_id,
                    timestamp=ended_at,
                    user_request=state.message,
                    context_scope=state.context,
                    agent=agent_label,
                    status=status,
                    routing_method=state.routing_method,
                    files_used=state.files_used,
                    tools_called=state.tools_called,
                    model_used=model if use_agent_runner else None,
                    result_summary=result_summary,
                    result_path=result_path,
                    context_path=context_path,
                    conversation_id=state.conversation_id,
                    duration_ms=duration_ms,
                    reflection_triggered=state.reflection_triggered,
                    reflection_improved=state.reflection_improved,
                    handoffs=handoffs_payload,
                    models_used=state.models_used,
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


class FinalizeMixin:
    """``_finalize_run`` / ``_finalize_run_safely`` bound to orchestrator settings."""

    def _finalize_run(
        self,
        *,
        state: RunState,
        ended_at: datetime,
        status: str,
        error_summary: str | None = None,
        result_body: str | None = None,
        suppress_persistence_errors: bool = False,
    ) -> None:
        finalize_orchestrator_run(
            state=state,
            ended_at=ended_at,
            status=status,
            dataset_path=self.dataset_path,
            run_log_store_context=self.run_log_store_context,
            db=self.db,
            model=self.model,
            use_agent_runner=self.use_agent_runner,
            reflection_min_tool_calls=self.reflection_min_tool_calls,
            error_summary=error_summary,
            result_body=result_body,
            suppress_persistence_errors=suppress_persistence_errors,
        )

    def _finalize_run_safely(self, **kwargs: object) -> None:
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
