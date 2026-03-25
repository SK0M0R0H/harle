"""Unit tests for harle.logging.artifacts.RunArtifactStore."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from harle.logging.artifacts import (
    RunArtifact,
    clear_run_artifact_store,
    pop_artifact,
    register_artifact,
)


def test_register_and_pop_returns_artifact() -> None:
    clear_run_artifact_store()
    try:
        ts = datetime(2026, 2, 19, 14, 30, 0, tzinfo=timezone.utc)
        a = RunArtifact(
            run_id="run_one",
            timestamp=ts,
            agent="secretary",
            status="completed",
            context_scope="work",
            result_body="Hello",
        )
        register_artifact(a)
        got = pop_artifact("run_one")
        assert got is not None
        assert got.run_id == "run_one"
        assert got.result_body == "Hello"
        assert pop_artifact("run_one") is None
    finally:
        clear_run_artifact_store()


def test_pop_missing_returns_none() -> None:
    clear_run_artifact_store()
    try:
        assert pop_artifact("none") is None
    finally:
        clear_run_artifact_store()


def test_clear_removes_all() -> None:
    register_artifact(
        RunArtifact(
            run_id="run_a",
            timestamp=datetime.now(timezone.utc),
            agent="x",
            status="completed",
            context_scope="work",
            result_body="",
        )
    )
    clear_run_artifact_store()
    assert pop_artifact("run_a") is None


def test_register_overwrites_same_run_id() -> None:
    clear_run_artifact_store()
    try:
        ts = datetime.now(timezone.utc)
        register_artifact(
            RunArtifact(
                run_id="run_x",
                timestamp=ts,
                agent="a",
                status="completed",
                context_scope="work",
                result_body="first",
            )
        )
        register_artifact(
            RunArtifact(
                run_id="run_x",
                timestamp=ts,
                agent="a",
                status="completed",
                context_scope="work",
                result_body="second",
            )
        )
        got = pop_artifact("run_x")
        assert got is not None
        assert got.result_body == "second"
    finally:
        clear_run_artifact_store()


def test_concurrent_register_pop() -> None:
    clear_run_artifact_store()
    try:
        errors: list[Exception] = []
        registered = threading.Barrier(10)

        def worker(i: int) -> None:
            try:
                rid = f"run_{i}"
                register_artifact(
                    RunArtifact(
                        run_id=rid,
                        timestamp=datetime.now(timezone.utc),
                        agent="t",
                        status="completed",
                        context_scope="work",
                        result_body=str(i),
                    )
                )
                registered.wait()
                got = pop_artifact(rid)
                if got is None or got.result_body != str(i):
                    errors.append(RuntimeError(f"bad pop for {rid}"))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
    finally:
        clear_run_artifact_store()
