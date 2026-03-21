---
title: "Harle Testing Strategy — Current State"
tags: [testing, current-state, strategy, ci-cd, pytest, implementation-status]
context: global
last_updated: 2026-03-21
summary: "Tracks what is implemented vs the Testing Strategy TRD and what each missing part would unlock."
---

# Harle Testing Strategy — Current State

> This document compares the target design in the Testing Strategy TRD with the current test setup. It describes what is implemented, what is partial, what is missing, and what each missing part would unlock.

Reference TRD: [Harle Testing Strategy — Best Practices & Implementation Plan](../trd/testing_strategy.md)

---

## Overall Status

**Foundation is in place:** unit tests for core modules (config, search, tools, context, API, etc.), an integration test suite with markers, shared fixtures in `conftest.py`, and a mock LLM (`EchoProvider`) for deterministic tests. **Missing:** linting/formatting/type-check automation (partially in CI), full coverage thresholds, semantic/LLM evaluation, Go CLI tests, and the full tooling stack (DeepEval, Promptfoo, ruff, mypy, pytest-cov). The TRD’s implementation roadmap (Phases 1–6) is largely not started.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| **§2 Current State (as baseline)** | Implemented | Unit tests in `tests/unit/`, pytest in pyproject, conftest fixtures, EchoProvider; tool tests thorough. |
| **§3 Four-layer model (concept)** | Document only | TRD defines layers; only Layer 1 and part of Layer 2 exist in code. |
| **§4 Layer 1: Unit tests** | Implemented | Many modules covered: config, tokenizer, reader, search, tools (registry, permissions, constraints, sandbox, skills, vault, web_search), API models, hasher, run_logger, providers, frontmatter. |
| **§5 Layer 2: Integration tests** | Partially implemented | `tests/integration/` with marker `integration`; includes `test_integration_flows.py` (API, search, context) and `test_plan_then_execute.py` (Level 3 orchestrator + vault + `POST /chat` with SDK stubs). Full TRD-style DB/container pipelines still partial. |
| **§6 Layer 3: Semantic / LLM evaluation** | Not implemented | No DeepEval, no golden datasets, no LLM-as-judge or relevancy/faithfulness metrics. |
| **§7 Layer 4: E2E tests** | Implemented (emulated) | `tests/e2e/` with real-server harness; session lifecycle, health, /chat (one-shot + multi-turn), vault tool via /search; CI runs E2E on PR to main and nightly. Live E2E (real LLM, real APIs) is planned in [E2E live extension](../trd/e2e-live-extension.md). |
| **§8 AI-assisted testing (Cursor)** | Partial | No `.cursor/rules/test_generation.mdc`; Cursor can be used ad hoc. |
| **§9 CI/CD — GitHub Actions** | Not implemented | No `.github/workflows/`; tests run only manually. |
| **§10 Tooling stack** | Partially implemented | pytest, httpx in use; no pytest-cov, pytest-asyncio, ruff, mypy, DeepEval, Promptfoo, pip-audit in config. |
| **§11 Test data management** | Partial | conftest has temp dirs and sample content; no fixture vault under `tests/fixtures/vault/`, no golden_datasets, no testcontainers/Postgres fixtures. |
| **§12 Implementation roadmap** | Not started | Phases 1–6 (CI, coverage, integration, semantic, E2E, hardening) not executed. |
| **§13 Metrics & coverage targets** | Not implemented | No coverage tracking, no thresholds, no quality dashboard. |
| **Go CLI tests** | Not implemented | No tests in harle-cli (if present). |
| **Pytest markers (full set)** | Partial | `integration` and `e2e` markers in pyproject; no `unit`, `semantic`. |

---

## What Is Implemented

### 1. Unit tests (Layer 1)

- **Location:** `tests/unit/` with many files: `test_config.py`, `test_search_engine.py`, `test_tools*.py`, `test_context.py`, `test_api.py`, `test_reader.py`, `test_hasher.py`, `test_orchestrator.py`, `test_providers.py`, `test_run_logger.py`, `test_models.py`, `test_frontmatter.py`, `test_imports.py`, `test_runs.py`.
- **Runner:** pytest configured in `pyproject.toml` with `testpaths = ["tests/unit", "tests/integration"]` and optional dependency `[test]` (pytest, httpx).
- **Fixtures:** `tests/conftest.py` provides shared fixtures (e.g. temp dataset dirs, sample Markdown) as in TRD §2.
- **Mock LLM:** `EchoProvider` (in `harle.llm.providers` or equivalent) used for deterministic orchestrator/LLM tests.
- **Tool module tests:** Strong coverage for registry, permissions, constraints, sandbox, skills, vault, web_search, security-oriented cases.

### 2. Integration test structure

- **Location:** `tests/integration/` with `test_integration_flows.py`, `test_plan_then_execute.py` (plan-then-execute / vault / routing), and `integration/conftest.py`.
- **Marker:** `integration` marker defined in `pyproject.toml` for multi-component tests.
- **Separation:** Unit vs integration split by directory and marker, as in TRD.

### 3. Test layout and conventions

- Test files align with source modules (e.g. `test_tools*.py` for `harle.tools`).
- Async tests use helpers (e.g. `_run()` for async) where needed.

### 4. E2E tests (Layer 4, emulated)

- **Location:** `tests/e2e/` with `conftest.py` (server fixture), `test_session.py` (health, /chat), `test_tool_flow.py` (chat completion), `test_vault.py` (vault tool: /search, /health/tools).
- **Harness:** Real HTTP server (uvicorn) started in a subprocess with `DATABASE_URL`, `HARLE_DATASET_PATH` (fixture vault under `tests/fixtures/e2e_vault` with `prompts/` filled from `src/harle/bootstrap_data/agent_prompts` at copy time), EchoProvider (no `OPENAI_API_KEY`). Skip when `DATABASE_URL` is unset.
- **CI:** E2E runs on every pull request to main (`.github/workflows/ci.yml` job `test-e2e`) and in nightly (`nightly.yml`).
- **Marker:** `e2e` in `pyproject.toml`. Live E2E (real LLM, real APIs) is planned in [E2E live extension](../trd/e2e-live-extension.md).

---

## What Is Partially Implemented

### 1. Integration tests (Layer 2)

- **Present:** Integration directory and marker; some integration flows.
- **Gap:** TRD describes full request→response pipeline tests (e.g. `TestClient` POST /chat, context assembly + search, tool registry → agent runner, DB operations, conversation flow). Current integration suite does not yet cover all these flows or use a test DB/container as in TRD.

### 2. Tooling stack

- **Present:** pytest, httpx.
- **Missing from TRD:** pytest-cov, pytest-asyncio, ruff, mypy, DeepEval, Promptfoo, pip-audit; optional `[dev]` and extended `[test]` deps not added.

### 3. Test data and fixtures

- **Present:** conftest fixtures for temp dirs and sample content.
- **Missing:** Dedicated fixture vault (`tests/fixtures/vault/` with prompts, policies, workflows, knowledge, tool_skills), golden datasets (`tests/golden_datasets/*.json`), and DB fixtures (in-memory SQLite for unit, Postgres/testcontainers for integration) as in TRD §11.

### 4. Pytest markers

- **Present:** `integration` marker.
- **Missing:** Explicit `unit`, `semantic`, `e2e` markers and CI jobs that run by marker (e.g. `pytest -m "not integration and not semantic and not e2e"` for fast unit-only runs).

### 5. AI-assisted testing (Cursor)

- TRD suggests a Cursor rule (e.g. `.cursor/rules/test_generation.mdc`) for consistent test generation and patterns. Not present; Cursor can still be used manually for test writing and review.

---

## What Is Not Implemented Yet

### 1. CI/CD pipeline (§9)

- **Missing:** `.github/workflows/ci.yml` (lint, type check, unit tests on push; integration + coverage on PR), nightly workflow (E2E emulated, semantic if prompts changed, pip-audit), pre-release workflow (full E2E, live LLM eval).
- **Unlocks:** Automated quality gates on every push/PR, regression detection before merge, dependency and security checks, consistent feedback for contributors.

### 2. Linting, formatting, and type checking

- **Missing:** ruff config in `pyproject.toml`, mypy config, and CI steps that run `ruff check`, `ruff format --check`, and `mypy`.
- **Unlocks:** Uniform style and type safety on main, fewer bugs and easier refactors.

### 3. Coverage measurement and thresholds (§13)

- **Missing:** pytest-cov, `--cov=harle --cov-report=xml --cov-fail-under=...`, and coverage upload (e.g. Codecov) in CI.
- **Unlocks:** Visibility into untested code, ability to enforce minimum coverage (e.g. 70% on PR) and track progress toward TRD targets.

### 4. Layer 3: Semantic / LLM evaluation (§6)

- **Missing:** DeepEval (or equivalent), golden datasets, semantic eval tests (relevancy, faithfulness, hallucination), and Promptfoo for prompt regression.
- **Unlocks:** Confidence that LLM outputs stay relevant and grounded when prompts or models change; prompt regression testing without full E2E.

### 5. Layer 4: E2E tests (§7)

- **Implemented (emulated):** `tests/e2e/` with real HTTP server (uvicorn), EchoProvider, Postgres and vault fixture; tests for health, /chat (one-shot + multi-turn), vault tool (/search, /health/tools), and chat completion. E2E runs on PR to main (ci.yml) and in nightly. Tool flow in emulated mode only validates completion (no real agent tool calls).
- **Not yet:** Live E2E (real OpenAI, Tavily, Trello), `docker-compose.test.yml`, error recovery / security boundary / concurrency scenarios. See [E2E live extension](../trd/e2e-live-extension.md) for the follow-on plan.

### 6. Go CLI tests

- **Missing:** Unit tests for CLI client, session manager, and commands in `harle-cli` (if the repo contains it); Go test job in CI.
- **Unlocks:** Safe evolution of the CLI and contract compatibility with the Orchestrator API.

### 7. API contract tests (CLI ↔ Orchestrator)

- **Missing:** Explicit contract tests (e.g. JSON schema or request/response validation) between CLI and Orchestrator.
- **Unlocks:** Fewer breakages when API or CLI changes.

### 8. Cursor rule for test generation (§8.1)

- **Missing:** `.cursor/rules/test_generation.mdc` with Harle-specific test patterns (EchoProvider, tmp_path, monkeypatch, markers, no integration unless asked).
- **Unlocks:** Consistent, TRD-aligned test generation when using Cursor for test writing.

### 9. Implementation roadmap execution (§12)

- **Missing:** Phases 1–6 (foundation, coverage expansion, integration, semantic eval, E2E + Go CLI, hardening) as scheduled deliverables.
- **Unlocks:** Incremental, ordered rollout of the full testing strategy and metrics from §13.

### 10. Metrics and quality targets (§13)

- **Missing:** Tracked line/branch coverage targets, semantic eval scores, CI duration and flaky rate, dependency audit (pip-audit) in CI.
- **Unlocks:** Clear quality goals and trend visibility.

---

## Key Deviations

- **Test paths:** TRD §2 mentions “18 test files in `tests/`”; current layout uses `tests/unit/` and `tests/integration/` with more than 18 files total. This is an evolution, not a conflict.
- **Optional test deps:** TRD lists pytest-asyncio, pytest-cov, deepeval in optional dependencies; current `[test]` only has pytest and httpx. Aligning with TRD would mean extending `[project.optional-dependencies]` and adding markers.

---

## Assessment

The codebase has a solid **Layer 1** and the beginnings of **Layer 2**, matching the TRD’s “current state” baseline. The largest gaps are **automation** (CI/CD, lint, type check, coverage) and **AI-specific testing** (semantic eval, E2E). Implementing Phase 1 (CI + linting + markers + coverage baseline) would immediately improve reliability and contributor experience; Phases 2–4 would then expand coverage and add semantic evaluation; Phases 5–6 would complete E2E, Go CLI, and hardening.
