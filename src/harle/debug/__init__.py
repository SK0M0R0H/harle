"""Harle execution tracing — structured hierarchical traces via OpenTelemetry.

Public API::

    from harle.debug import etrace

    with etrace.span("handle_request", level=etrace.STEP, module="orchestrator"):
        etrace.step("Routed to agent", agent="secretary")
        etrace.detail("Token budget", used=3420, total=4096)
"""

from harle.debug import trace as etrace
from harle.debug.levels import TraceLevel
from harle.debug.setup import configure_tracing

__all__ = ["etrace", "configure_tracing", "TraceLevel"]
