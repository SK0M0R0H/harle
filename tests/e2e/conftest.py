"""Shared fixtures for Harle E2E tests.

Starts a real server process (uvicorn) with EchoProvider and optional
Postgres + vault. Skips the module when DATABASE_URL is not set.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Repo root: tests/e2e/conftest.py -> tests -> repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_E2E_VAULT = _REPO_ROOT / "tests" / "fixtures" / "e2e_vault"


def _free_port() -> int:
    """Return a free port for the server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_health(
    base_url: str,
    attempts: int = 60,
    sleep: float = 2.0,
    timeout: float = 10.0,
) -> bool:
    """Return True when GET base_url/health returns 200.

    The first request triggers create_app() and ensure_initialized() (DB + vault
    indexing), which can take 30–90 seconds on a cold run; we retry long enough
    for that to complete.
    """
    import httpx

    for _ in range(attempts):
        try:
            r = httpx.get(f"{base_url}/health", timeout=timeout)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(sleep)
    return False


@pytest.fixture(scope="session")
def e2e_base_url() -> str:
    """Start the Harle server and yield its base URL; skip when DATABASE_URL is unset."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip(
            "DATABASE_URL is not set; E2E tests require Postgres (e.g. CI or local Docker)."
        )

    if not _E2E_VAULT.is_dir():
        pytest.skip(f"E2E vault not found: {_E2E_VAULT}")

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["HARLE_DATASET_PATH"] = str(_E2E_VAULT)
    env["HARLE_PORT"] = str(port)
    # E2E-only config: no DATABASE_URL so env wins; avoids repo config/.env overriding test URL
    env["HARLE_CONFIG_PATH"] = str(_REPO_ROOT / "tests" / "e2e" / "config_e2e.yaml")
    env["HARLE_DOTENV_PATH"] = str(_REPO_ROOT / "tests" / "e2e" / ".env.e2e")
    # Force EchoProvider so E2E is deterministic and fast (override .env if present)
    env["OPENAI_API_KEY"] = ""
    # Ensure the subprocess can import harle (CI does pip install -e .; local may rely on PYTHONPATH)
    src = _REPO_ROOT / "src"
    env["PYTHONPATH"] = os.pathsep.join([str(src), env.get("PYTHONPATH", "")])
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "harle.main:create_app", "--factory", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(_REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    try:
        if not _wait_for_health(base_url):
            stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            proc.terminate()
            proc.wait(timeout=5)
            hint = ""
            if "password authentication failed" in stderr or "OperationalError" in stderr:
                hint = (
                    "\n\nIf you see 'password authentication failed': DATABASE_URL must match "
                    "your Postgres (user, password, dbname). If the container was created earlier "
                    "with different env, remove it and its volume and run a fresh container so "
                    "POSTGRES_PASSWORD is applied (e.g. docker rm -f harle_test; docker run ...). "
                    "If another Postgres is on port 5432, use a different port (e.g. -p 5433:5432) "
                    "and set DATABASE_URL to that port."
                )
            pytest.fail(f"Server did not become healthy at {base_url}. stderr:\n{stderr}{hint}")
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
