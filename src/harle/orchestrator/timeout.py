"""Wall-clock timeouts and error summaries for orchestrator runs."""

from __future__ import annotations

import logging
import signal
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from contextlib import contextmanager
from typing import Callable, TypeVar

_OnTimeout = Callable[[], None]

from harle.orchestrator.state import RESULT_SUMMARY_MAX_CHARS, RunTimeoutError

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


def safe_error_summary(exc: Exception) -> str:
    """Build a short, safe error summary for failed run persistence."""
    message = " ".join(str(exc).split()).strip()
    summary = exc.__class__.__name__
    if message:
        summary = f"{summary}: {message}"
    if len(summary) > RESULT_SUMMARY_MAX_CHARS:
        return summary[:RESULT_SUMMARY_MAX_CHARS] + "..."
    return summary


def timeout_summary(duration_ms: int | None) -> str:
    """Build a short timeout summary with elapsed time when available."""
    if duration_ms is None:
        return "Run timed out before completion"
    return f"Run timed out before completion (elapsed: {duration_ms} ms)"


@contextmanager
def run_timeout(seconds: int | None) -> object:
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


def run_with_timeout(
    seconds: int | None,
    thunk: Callable[[], _T],
    *,
    on_timeout: _OnTimeout | None = None,
) -> _T:
    """Run a callable under a wall-clock timeout that works in any thread.

    On the main thread uses SIGALRM; on worker threads (e.g. under
    run_in_threadpool) runs the thunk in a separate thread and waits
    with timeout so the server-side limit is enforced in production.

    When the worker-thread limit is exceeded, the executor is shut down
    without waiting for the thunk to finish.  Callers may pass *on_timeout*
    to signal cooperative abort (e.g. skip late persistence).
    """
    if not seconds or seconds <= 0:
        return thunk()

    if threading.current_thread() is threading.main_thread():
        with run_timeout(seconds):
            return thunk()

    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(thunk)
    try:
        return future.result(timeout=seconds)
    except FuturesTimeoutError:
        if on_timeout is not None:
            on_timeout()
        raise RunTimeoutError("Run timed out before completion")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
