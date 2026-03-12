"""Harle debug logging — structured hierarchical traces via OpenTelemetry.

Public API::

    from harle.debug import dtrace

    with dtrace.span("handle_request", level=dtrace.STEP, module="orchestrator"):
        dtrace.step("Routed to agent", agent="secretary")
        dtrace.detail("Token budget", used=3420, total=4096)
"""

from harle.debug import trace as dtrace
from harle.debug.levels import TraceLevel
from harle.debug.setup import configure_tracing

__all__ = ["dtrace", "configure_tracing", "TraceLevel"]
