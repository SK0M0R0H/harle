"""Request orchestrator for Harle.

Coordinates context assembly, conversation management, and LLM
generation for every user request via the chat pipeline (create or
load conversation, assemble context including history when present,
execute, persist messages).

Execution uses one of two LLM backends:

1. **Agent Runner** (Level 1+): OpenAI Agents SDK ``Runner`` for
   multi-step reasoning with tool calls when an OpenAI API key is set.

2. **Legacy provider** (fallback): Single LLM call via
   ``LLMProvider`` (e.g. echo provider when no API key).

When a :class:`ToolRegistry` is provided, the agent receives
SDK-compatible tool functions and can call them during reasoning.

Implementation is split across ``state``, ``timeout``, ``finalize``,
``execution``, ``chat``, ``orchestrator_service``, and ``builder`` for
maintainability; this module re-exports the public API.
"""

from __future__ import annotations

from harle.orchestrator.builder import build_orchestrator
from harle.orchestrator.orchestrator_service import OrchestratorService
from harle.orchestrator.state import (
    DEFAULT_AGENT_ROLE,
    RESULT_SUMMARY_MAX_CHARS,
    AgentResult as _AgentResult,
    RunState as _RunState,
    RunTimeoutError,
)
from harle.orchestrator.timeout import (
    run_with_timeout as _run_with_timeout,
    safe_error_summary as _safe_error_summary,
    timeout_summary as _timeout_summary,
)

__all__ = [
    "OrchestratorService",
    "RunTimeoutError",
    "build_orchestrator",
    "DEFAULT_AGENT_ROLE",
    "RESULT_SUMMARY_MAX_CHARS",
    "_AgentResult",
    "_RunState",
    "_run_with_timeout",
    "_safe_error_summary",
    "_timeout_summary",
]
