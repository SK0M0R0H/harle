"""``etrace`` — thin convenience API over OpenTelemetry for Harle execution tracing.

Every ``etrace.`` call in the codebase is execution-trace instrumentation — not
business logic.  The prefix serves as a visual marker: you can skip
all ``etrace.*`` lines when reading for functionality, or focus on
them when reading for observability.

Under the hood each function translates directly to OTel span
operations.  When no ``TracerProvider`` is configured (tests, scripts),
OTel returns ``NoOpSpan`` instances — zero cost, zero side effects.
"""

from __future__ import annotations

import json
import functools
from contextlib import contextmanager
from typing import Any, Callable, Generator, TypeVar

from opentelemetry import trace

from harle.debug.levels import TraceLevel

_tracer = trace.get_tracer("harle")

STEP = TraceLevel.STEP
DETAIL = TraceLevel.DETAIL
TRACE = TraceLevel.TRACE
INTERNAL = TraceLevel.INTERNAL

F = TypeVar("F", bound=Callable[..., Any])


def _serialize_attr(value: Any) -> str | int | float | bool:
    """Coerce an attribute value to an OTel-compatible primitive.

    OTel span attributes accept ``str | int | float | bool`` and
    sequences of those types.  Anything else is JSON-serialized.
    """
    if isinstance(value, (str, int, float, bool)):
        return value
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _set_attrs(span: trace.Span, level: TraceLevel, module: str, attrs: dict[str, Any]) -> None:
    """Set standard Harle attributes plus caller-supplied extras."""
    span.set_attribute("harle.level", level.name)
    if module:
        span.set_attribute("harle.module", module)
    for key, value in attrs.items():
        span.set_attribute(key, _serialize_attr(value))


@contextmanager
def span(
    name: str,
    *,
    level: TraceLevel = STEP,
    module: str = "",
    **attrs: Any,
) -> Generator[trace.Span, None, None]:
    """Open a span that parents any ``etrace`` calls made inside.

    Usage::

        with etrace.span("context_assembly", level=etrace.STEP, module="context"):
            etrace.detail("Loaded 3 policies", count=3)
    """
    with _tracer.start_as_current_span(name) as otel_span:
        _set_attrs(otel_span, level, module, attrs)
        yield otel_span


def _emit_leaf(name: str, *, level: TraceLevel, module: str = "", **attrs: Any) -> None:
    """Create a leaf span (immediately opened and closed)."""
    with _tracer.start_as_current_span(name) as s:
        _set_attrs(s, level, module, attrs)


def step(name: str, *, module: str = "", **attrs: Any) -> None:
    """Emit a STEP-level leaf span — major processing stage."""
    _emit_leaf(name, level=STEP, module=module, **attrs)


def detail(name: str, *, module: str = "", **attrs: Any) -> None:
    """Emit a DETAIL-level leaf span — decisions, parameters, intermediate results."""
    _emit_leaf(name, level=DETAIL, module=module, **attrs)


def trace_entry(name: str, *, module: str = "", **attrs: Any) -> None:
    """Emit a TRACE-level leaf span — fine-grained internals.

    Named ``trace_entry`` instead of ``trace`` to avoid shadowing the
    ``opentelemetry.trace`` module and the Python builtin.
    """
    _emit_leaf(name, level=TRACE, module=module, **attrs)


def internal(name: str, *, module: str = "", **attrs: Any) -> None:
    """Emit an INTERNAL-level leaf span — very low-level, dev-only."""
    _emit_leaf(name, level=INTERNAL, module=module, **attrs)


def span_fn(
    *,
    level: TraceLevel = STEP,
    module: str = "",
    name: str | None = None,
) -> Callable[[F], F]:
    """Decorator that wraps a function in an auto-named span.

    Usage::

        @etrace.span_fn(level=etrace.STEP, module="orchestrator")
        async def route(request: RunRequest) -> str:
            ...
    """

    def decorator(fn: F) -> F:
        span_name = name or fn.__name__

        if _is_coroutine_function(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with span(span_name, level=level, module=module):
                    return await fn(*args, **kwargs)
            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with span(span_name, level=level, module=module):
                return fn(*args, **kwargs)
        return sync_wrapper  # type: ignore[return-value]

    return decorator


def _is_coroutine_function(fn: Any) -> bool:
    """Check if *fn* is an async function (or async-wrapped)."""
    import asyncio
    return asyncio.iscoroutinefunction(fn)
