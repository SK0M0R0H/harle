---
title: "Harle Testing Strategy — Best Practices & Implementation Plan"
tags: [testing, strategy, ci-cd, automation, ai-testing, quality, pytest, cursor]
context: global
last_updated: 2026-03-19
summary: "Comprehensive testing strategy for Harle covering unit, integration, semantic, and E2E testing layers, AI-assisted workflows with Cursor, and CI/CD automation with GitHub Actions."
---

# Harle Testing Strategy — Best Practices & Implementation Plan

> A reliable AI assistant must itself be reliably tested. This document defines Harle's testing philosophy, architecture, tooling, and implementation roadmap — including how to leverage AI (Cursor) as a force multiplier for test development and maintenance.

---

## Table of Contents

1. [Why Testing Harle Is Different](#1-why-testing-harle-is-different)
2. [Current State](#2-current-state)
3. [Testing Architecture — The Four-Layer Model](#3-testing-architecture--the-four-layer-model)
4. [Layer 1: Unit Tests](#4-layer-1-unit-tests)
5. [Layer 2: Integration Tests](#5-layer-2-integration-tests)
6. [Layer 3: Semantic / LLM Evaluation Tests](#6-layer-3-semantic--llm-evaluation-tests)
7. [Layer 4: End-to-End (E2E) Tests](#7-layer-4-end-to-end-e2e-tests)
8. [AI-Assisted Testing with Cursor](#8-ai-assisted-testing-with-cursor)
9. [CI/CD Pipeline — GitHub Actions](#9-cicd-pipeline--github-actions)
10. [Tooling Stack](#10-tooling-stack)
11. [Test Data Management](#11-test-data-management)
12. [Implementation Roadmap](#12-implementation-roadmap)
13. [Metrics & Coverage Targets](#13-metrics--coverage-targets)

---

## 1. Why Testing Harle Is Different

Harle is not a typical CRUD application. Testing it presents challenges unique to AI-agent systems:

| Challenge | Why it matters | Impact on testing |
|---|---|---|
| **Non-deterministic LLM outputs** | The same prompt produces different text each time. Exact-match assertions fail. | Requires semantic evaluation instead of string comparison. |
| **Multi-component pipeline** | A single request flows through Router → Clarifier → Context Assembler → Agent Runner → Tool calls → Run Logger. | Each component needs isolated tests AND end-to-end flow tests. |
| **External API dependencies** | OpenAI, Trello, Tavily/Bing APIs can be slow, rate-limited, or down. | Tests must mock external calls for speed; a separate suite validates real connections. |
| **Stateful conversations** | Multi-turn chat accumulates context. Behavior depends on history. | Tests must simulate multi-turn flows with conversation state. |
| **Security-critical tools** | The Scripts module executes code on the host. The Vault module writes to user files. | Security constraints need adversarial test cases (prompt injection, path traversal). |
| **Dual codebase** | Python (Orchestrator) and Go (CLI) are separate projects with different toolchains. | Each needs its own test suite; contract tests verify API compatibility. |

These challenges make a layered testing approach essential — no single type of test covers everything.

---

## 2. Current State

**What exists today:**

| Area | Status | Files |
|---|---|---|
| **Unit tests (Python)** | Good coverage for core modules | 18 test files in `tests/` |
| **Test runner** | pytest configured | `pyproject.toml` [tool.pytest.ini_options] |
| **conftest.py** | Shared fixtures (temp dataset dirs, sample Markdown) | `tests/conftest.py` |
| **Mock LLM** | `EchoProvider` for deterministic orchestrator tests | `harle.llm.providers` |
| **Tool Module tests** | Thorough: registry, permissions, constraints, sandbox, skills | `test_tools*.py` (4 files, ~1500 lines) |
| **Go CLI tests** | None yet | — |
| **CI/CD** | None configured | No `.github/workflows/` |
| **Linting/formatting** | No automated checks | No ruff/black/mypy config |
| **Semantic/LLM evaluation** | Not implemented | — |
| **E2E tests** | Not implemented | — |
| **Coverage tracking** | Not configured | — |

**What's missing (and this document addresses):**

1. No CI/CD pipeline — tests run only manually.
2. No linting or type-checking automation.
3. No coverage measurement or enforcement.
4. No semantic evaluation layer for LLM outputs.
5. No Go CLI tests.
6. No API contract tests between CLI and Orchestrator.
7. No prompt regression testing.
8. No production monitoring or drift detection.

---

## 3. Testing Architecture — The Four-Layer Model

```
┌────────────────────────────────────────────────────────────────────────┐
│                        LAYER 4: E2E TESTS                              │
│  Full pipeline: CLI → HTTP → Orchestrator → LLM → Tools → Response    │
│  Runs against real or emulated services. Slow, expensive.              │
│  Frequency: pre-release, nightly (CI).                                 │
└────────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────────┐
│                  LAYER 3: SEMANTIC / LLM EVALUATION                    │
│  Validates LLM output quality: relevance, correctness, hallucination.  │
│  Uses LLM-as-judge, embedding similarity, golden datasets.             │
│  Frequency: on prompt changes, weekly.                                 │
└────────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────────┐
│                    LAYER 2: INTEGRATION TESTS                          │
│  Multi-module flows with mocked external deps (LLM, APIs).            │
│  Orchestrator pipeline, tool registry wiring, DB operations.           │
│  Frequency: every PR (CI).                                             │
└────────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────────┐
│                       LAYER 1: UNIT TESTS                              │
│  Single function/class in isolation. Fast, deterministic.              │
│  Config, tokenizer, constraints, frontmatter, search, permissions.     │
│  Frequency: every commit (CI).                                         │
└────────────────────────────────────────────────────────────────────────┘
```

**Time and cost allocation:**

| Layer | Runtime | Proportion of tests | Cost per run | Trigger |
|---|---|---|---|---|
| **Unit** | < 30 seconds | ~50% | Free | Every push |
| **Integration** | 1–3 minutes | ~30% | Free (mocked LLM) | Every PR |
| **Semantic/LLM eval** | 5–15 minutes | ~15% | ~$0.50–2 (LLM-as-judge API calls) | Prompt changes, weekly |
| **E2E** | 10–30 minutes | ~5% | ~$1–5 (real LLM calls) | Pre-release, nightly |

---

## 4. Layer 1: Unit Tests

Unit tests validate individual functions and classes in isolation. They are the foundation — fast, deterministic, and cheap to run.

### What to unit test in Harle

| Module | Key test targets | Approach |
|---|---|---|
| `harle.config` | Settings loading, env var substitution, defaults, validation | Use `monkeypatch` for env vars, temp config files |
| `harle.context.tokenizer` | Token counting accuracy across models | Direct assertions on known strings |
| `harle.context.assembler` | Priority-based context packing, budget enforcement, trimming | Inject mock search results and prompts |
| `harle.dataset.reader` | File discovery, frontmatter parsing, filtering | Temp directories with fixture files |
| `harle.dataset.writer` | File creation, frontmatter injection, path safety | Temp directories, verify file contents |
| `harle.search.*` | Whoosh index operations, query expansion, ranking | In-memory Whoosh index with fixture data |
| `harle.tools.constraints` | All constraint checks (paths, patterns, commands, hosts) | Adversarial inputs, edge cases |
| `harle.tools.sandbox` | Timeout enforcement, output truncation, resource limits | Real subprocess calls with safe commands |
| `harle.tools.permissions` | Permission checking, operation modes, approval flow | Direct function calls |
| `harle.tools.skills` | Skill loading, resolution, override logic, token budgets | Temp directories, mock vault |
| `harle.tools.registry` | Registration, conflicts, FunctionTool generation | Dummy modules |
| `harle.db.models` | SQLAlchemy model definitions | In-memory SQLite |
| `harle.api.models` | Pydantic model validation (request/response schemas) | Direct construction with valid/invalid data |
| `harle.indexing.*` | Hashing, summarization, indexer pipeline | Fixture files, mock LLM for summarizer |

### Best practices for Harle unit tests

1. **No network calls.** Every external dependency (OpenAI, Trello, Tavily, PostgreSQL) must be mocked or replaced with an in-memory alternative.
2. **Use `EchoProvider` for LLM calls.** The existing `EchoProvider` returns the input as output — deterministic and free. Use it for all unit tests involving the orchestrator.
3. **Use `tmp_path` for filesystem tests.** Pytest's `tmp_path` fixture provides isolated temp directories. Never write to real paths.
4. **Use `monkeypatch` for environment variables.** Never modify `os.environ` directly.
5. **Test both happy and error paths.** Every `ConstraintViolation`, `ToolRegistryError`, and validation failure should have a test.
6. **Keep test files parallel to source modules.** `test_tools.py` for `harle.tools`, `test_config.py` for `harle.config`, etc.

### Example: testing a new tool module

When adding a new tool module (e.g., GitHub), write tests following this checklist:

```python
class TestGitHubModule:
    """Tests for the GitHub tool module."""

    def test_implements_base_interface(self):
        mod = GitHubModule()
        assert hasattr(mod, "name")
        assert hasattr(mod, "get_tools")

    def test_tool_functions_have_docstrings(self):
        mod = GitHubModule()
        for fn in mod.get_tools():
            assert fn.__doc__, f"{fn.__name__} missing docstring"

    def test_tool_functions_have_type_hints(self):
        mod = GitHubModule()
        for fn in mod.get_tools():
            hints = get_type_hints(fn)
            assert "return" in hints, f"{fn.__name__} missing return type"

    def test_health_check_with_invalid_token(self):
        mod = GitHubModule()
        _run(mod.initialize({"api_token": "invalid"}))
        assert _run(mod.health_check()) is False

    def test_tools_register_in_registry(self):
        registry = ToolRegistry()
        mod = GitHubModule()
        registry.register_module(mod)
        assert all(
            name in registry for name in ["list_prs", "get_pr", "pr_summary"]
        )
```

---

## 5. Layer 2: Integration Tests

Integration tests verify that multiple components work together correctly. They focus on module boundaries and data flow through the pipeline.

### What to integration test

| Flow | Components involved | How to test |
|---|---|---|
| **Request → Response pipeline** | API routes → OrchestratorService → EchoProvider → Response | `httpx.AsyncClient` with FastAPI `TestClient` |
| **Context assembly** | ContextAssembler + DatasetReader + SearchEngine | Real Whoosh index on temp dataset, mock LLM |
| **Tool Registry → Agent Runner** | ToolRegistry → FunctionTool generation → Agent SDK acceptance | Register real modules, verify SDK objects |
| **Database operations** | Connection → Models → CRUD operations | In-memory SQLite or test PostgreSQL container |
| **Config → Bootstrap** | Settings loading → Orchestrator construction → Module initialization | Real config file with test values |
| **Search pipeline** | Query → Whoosh index → Ranker → Results | Indexed temp dataset |
| **Conversation flow** | Multiple requests → DB conversation state → Context includes history | Sequential API calls with conversation_id |

### Integration test conventions

1. **Marker-based separation.** Use `@pytest.mark.integration` to distinguish from unit tests. CI runs unit tests on every push, integration on every PR.
2. **Fixture hierarchy.** Integration fixtures build on unit fixtures. A `configured_orchestrator` fixture composes `dataset_dir`, `echo_provider`, and a real `ContextAssembler`.
3. **Database isolation.** Each test gets a fresh DB state. Use SQLAlchemy's `begin_nested()` + rollback pattern, or an in-memory SQLite.
4. **No real LLM calls.** Integration tests still use `EchoProvider` or pre-recorded responses. Real LLM calls are Layer 3/4.

### Example: API integration test

```python
@pytest.mark.integration
class TestRunEndpoint:
    def test_post_run_returns_completed(self, test_client):
        response = test_client.post("/chat", json={
            "message": "Find stalled tasks",
            "context": "work",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["run_id"].startswith("run_")

    def test_post_run_invalid_context_returns_422(self, test_client):
        response = test_client.post("/chat", json={
            "message": "hello",
            "context": "invalid_context",
        })
        assert response.status_code == 422
```

---

## 6. Layer 3: Semantic / LLM Evaluation Tests

This is the layer unique to AI applications. Traditional assertions cannot validate LLM output quality — you need semantic evaluation.

### The core problem

```python
# This will FAIL even when the output is perfectly correct:
assert response == "Found 7 stalled tasks. Here are suggested reformulations..."

# Because the LLM might return an equally valid:
# "I identified 7 tasks with no recent activity. Below are my recommendations..."
```

### Recommended tool: DeepEval

[DeepEval](https://deepeval.com) is an open-source pytest-native framework for LLM testing. It provides metrics that evaluate output quality without exact-match assertions.

**Installation:**

```bash
pip install deepeval
```

**Integration with existing pytest setup:**

```toml
# pyproject.toml additions
[project.optional-dependencies]
test = [
    "pytest>=8.0",
    "httpx>=0.27",
    "deepeval>=2.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "unit: fast, deterministic tests (no LLM calls)",
    "integration: multi-component tests (mocked LLM)",
    "semantic: LLM evaluation tests (requires API key, costs money)",
    "e2e: full pipeline tests (requires running services)",
]
```

### What to evaluate with DeepEval

| Metric | What it measures | When to use |
|---|---|---|
| **Answer Relevancy** | Does the output address the input question? | Every agent response |
| **Faithfulness** | Is the output grounded in the provided context (not hallucinated)? | Research reports, dataset-based answers |
| **Contextual Relevancy** | Was the right context retrieved and used? | Context Assembler quality |
| **Hallucination** | Does the output contain fabricated facts? | Any factual claim |
| **Tool Correctness** | Did the agent call the right tools with correct arguments? | Tool-using agent flows |
| **GEval (custom criteria)** | Arbitrary evaluation criteria you define | Domain-specific quality checks |

### Example: semantic evaluation test

```python
import pytest
from deepeval import assert_test
from deepeval.test_case import LLMTestCase
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric

@pytest.mark.semantic
class TestSecretaryOutputQuality:
    """Evaluate Secretary agent output quality against golden datasets."""

    @pytest.fixture
    def relevancy_metric(self):
        return AnswerRelevancyMetric(threshold=0.7)

    @pytest.fixture
    def faithfulness_metric(self):
        return FaithfulnessMetric(threshold=0.8)

    def test_task_triage_relevancy(self, relevancy_metric):
        test_case = LLMTestCase(
            input="Find stalled tasks in Trello and suggest reformulations",
            actual_output=run_secretary_agent("Find stalled tasks..."),
            retrieval_context=["Task triage workflow: ..."],
        )
        assert_test(test_case, [relevancy_metric])

    def test_research_report_faithfulness(self, faithfulness_metric):
        context = ["Source document about privacy policies..."]
        test_case = LLMTestCase(
            input="Summarize our privacy approach",
            actual_output=run_researcher_agent("Summarize...", context),
            retrieval_context=context,
        )
        assert_test(test_case, [faithfulness_metric])
```

### Golden datasets for regression testing

Maintain a collection of input-output pairs that define expected behavior. When prompts change, run the full golden dataset to detect regressions.

```
tests/
├── golden_datasets/
│   ├── secretary_triage.json      # Task triage scenarios
│   ├── researcher_reports.json    # Research report quality
│   └── routing_decisions.json     # Router classification accuracy
```

Each entry:

```json
{
    "input": "Find stalled Trello tasks for the Japan trip",
    "context": "work",
    "expected_agent": "secretary",
    "expected_tools": ["search_cards"],
    "quality_criteria": {
        "mentions_stalled_threshold": true,
        "includes_actionable_suggestions": true,
        "uses_provided_context": true
    }
}
```

### Prompt regression testing with Promptfoo

For testing prompt changes independently of the full pipeline, [Promptfoo](https://promptfoo.dev) provides a lightweight YAML-based evaluation framework:

```yaml
# promptfoo/secretary_triage.yaml
prompts:
  - file://src/harle/prompts/secretary.md

providers:
  - openai:gpt-4o-mini

tests:
  - vars:
      task: "Find stalled tasks in Trello"
    assert:
      - type: contains
        value: "stalled"
      - type: llm-rubric
        value: "Response provides actionable suggestions for each stalled task"

  - vars:
      task: "Summarize my week"
    assert:
      - type: llm-rubric
        value: "Response is organized by day or category"
```

Run: `npx promptfoo eval -c promptfoo/secretary_triage.yaml`

---

## 7. Layer 4: End-to-End (E2E) Tests

E2E tests validate the full pipeline from CLI to response, using real or realistic services.

### E2E test architecture

```
┌──────────┐     ┌───────────────┐     ┌──────────┐     ┌──────────┐
│  Test     │────>│  Orchestrator │────>│  Real or │────>│  Real or │
│  harness  │     │  (real server)│     │  mock LLM│     │  mock    │
│  (httpx)  │     │               │     │          │     │  tools   │
└──────────┘     └───────────────┘     └──────────┘     └──────────┘
                        │
                   ┌────▼────┐
                   │  Test   │
                   │  Postgres│
                   │ (Docker) │
                   └─────────┘
```

### Two E2E modes

| Mode | External services | When to use | Cost |
|---|---|---|---|
| **Emulated** | `EchoProvider` for LLM, mocked tool APIs, SQLite DB | PR validation, nightly CI | Free |
| **Live** | Real OpenAI API, real Trello API, real PostgreSQL | Pre-release validation, weekly | $1–5 per run |

### E2E test scenarios

1. **Session lifecycle**: Start session → send message → receive response → send follow-up → quit.
2. **Conversation context**: Verify multi-turn conversations maintain context correctly.
3. **Tool call flow**: Request that triggers a tool call → verify tool is called → verify result is incorporated.
4. **Error recovery**: LLM API timeout → verify graceful error message returned.
5. **Security boundary**: Request attempting path traversal via tool → verify blocked.
6. **Concurrent requests**: Multiple requests in parallel → verify no state corruption.

### Docker-based test environment

```yaml
# docker-compose.test.yml
services:
  orchestrator:
    build: .
    environment:
      - DATABASE_URL=postgresql+asyncpg://harle:test@db:5432/harle_test
      - OPENAI_API_KEY=${OPENAI_API_KEY:-echo}
      - HARLE_DATASET_PATH=/data/vault
    volumes:
      - ./tests/fixtures/vault:/data/vault:ro
    depends_on:
      db:
        condition: service_healthy

  db:
    image: pgvector/pgvector:pg16
    environment:
      - POSTGRES_USER=harle
      - POSTGRES_PASSWORD=test
      - POSTGRES_DB=harle_test
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U harle -d harle_test"]
      interval: 2s
      timeout: 5s
      retries: 5
```

---

## 8. AI-Assisted Testing with Cursor

Cursor (with your subscription) is a powerful testing force multiplier. Here is how to leverage it systematically.

### 8.1 Cursor rules for test generation

Create a Cursor rule that guides test generation for Harle:

```markdown
# .cursor/rules/test_generation.mdc

When generating tests for Harle:
1. Follow the existing test patterns in tests/ — use _run() for async,
   class-based test organization, DummyModule for tool tests.
2. Mock all external dependencies (LLM, APIs, DB).
3. Use EchoProvider for orchestrator tests, not real OpenAI calls.
4. Use tmp_path for filesystem operations.
5. Use monkeypatch for environment variables.
6. Test both success and error/edge cases.
7. Add @pytest.mark.integration for multi-component tests.
8. Follow the existing naming: test_<module>.py or test_<module>_<aspect>.py.
9. Do NOT add integration tests unless explicitly asked.
```

### 8.2 Test generation workflow

Use Cursor Agent mode for test development:

1. **"Write unit tests for `harle.search.engine`"** — Cursor reads the source module and existing test patterns, then generates tests following `conftest.py` conventions.
2. **"Add edge case tests for the Context Assembler's token budget enforcement"** — Cursor understands the token budget logic and generates boundary condition tests.
3. **"Generate a golden dataset for Secretary agent triage scenarios"** — Cursor creates realistic test scenarios based on the architecture docs.

### 8.3 Test review with Cursor

After writing code, ask Cursor:
- *"What test cases am I missing for this module?"*
- *"Review this test file for gaps — are there edge cases not covered?"*
- *"Generate adversarial inputs for the constraint engine"*

### 8.4 Test maintenance

When refactoring code, Cursor can:
- Automatically update test assertions when function signatures change.
- Identify broken tests and suggest fixes.
- Generate missing tests for new code paths detected via coverage reports.

### 8.5 AI-powered code review for tests

Before merging, use Cursor to review test quality:
- *"Is this test actually testing the right behavior, or just testing the mock?"*
- *"Does this integration test have hidden dependencies on execution order?"*
- *"Are there flaky test patterns in this file?"*

---

## 9. CI/CD Pipeline — GitHub Actions

### Pipeline architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ON PUSH (any branch)                      │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │ Lint + Type  │  │ Unit Tests   │  │ Security Scan          │  │
│  │  Check       │  │ (Python)     │  │ (secrets, deps)        │  │
│  │  ruff, mypy  │  │ pytest -m    │  │                        │  │
│  │              │  │ "not integ.."│  │                        │  │
│  └──────────────┘  └──────────────┘  └────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     ON PULL REQUEST (to main)                     │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │ All above +  │  │ Integration  │  │ Coverage Check         │  │
│  │              │  │ Tests        │  │ (fail if < threshold)  │  │
│  │              │  │ (with DB)    │  │                        │  │
│  └──────────────┘  └──────────────┘  └────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    NIGHTLY (scheduled)                            │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │ E2E Tests   │  │ Semantic     │  │ Dependency Audit       │  │
│  │ (emulated)  │  │ Eval (if     │  │ (pip-audit)            │  │
│  │             │  │ prompts      │  │                        │  │
│  │             │  │ changed)     │  │                        │  │
│  └─────────────┘  └──────────────┘  └────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                   PRE-RELEASE (manual trigger or tag)             │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │ Full E2E    │  │ Live LLM     │  │ Docker Build & Push    │  │
│  │ (with real  │  │ Eval Suite   │  │                        │  │
│  │ services)   │  │              │  │                        │  │
│  └─────────────┘  └──────────────┘  └────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### GitHub Actions workflow: CI (every push)

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: ["**"]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install ruff mypy
      - run: ruff check src/ tests/
      - run: ruff format --check src/ tests/
      - run: mypy src/harle/ --ignore-missing-imports

  test-unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[test]"
      - run: pytest -m "not integration and not semantic and not e2e" -v --tb=short

  test-integration:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: harle
          POSTGRES_PASSWORD: test
          POSTGRES_DB: harle_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U harle -d harle_test"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[test]"
      - run: pytest -m "integration" -v --tb=short
        env:
          DATABASE_URL: postgresql://harle:test@localhost:5432/harle_test

  coverage:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[test]" pytest-cov
      - run: >
          pytest
          -m "not semantic and not e2e"
          --cov=harle
          --cov-report=xml
          --cov-fail-under=70
      - uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml
```

### GitHub Actions workflow: nightly

```yaml
# .github/workflows/nightly.yml
name: Nightly

on:
  schedule:
    - cron: "0 3 * * *"  # 3 AM UTC daily
  workflow_dispatch:

jobs:
  e2e-emulated:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: harle
          POSTGRES_PASSWORD: test
          POSTGRES_DB: harle_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U harle -d harle_test"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[test]"
      - run: pytest -m "e2e" -v --tb=long
        env:
          DATABASE_URL: postgresql://harle:test@localhost:5432/harle_test

  dependency-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install pip-audit
      - run: pip-audit -r <(pip freeze) --fix --dry-run || true
```

### Go CLI testing in CI

```yaml
  test-cli:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with:
          go-version: "1.22"
      - run: go test ./...
        working-directory: harle-cli
      - run: go vet ./...
        working-directory: harle-cli
```

### Secrets management

| Secret | GitHub Secrets name | Used by |
|---|---|---|
| OpenAI API key | `OPENAI_API_KEY` | Semantic eval, live E2E |
| Trello API key | `TRELLO_API_KEY` | Live E2E (Trello module) |
| Trello API token | `TRELLO_API_TOKEN` | Live E2E (Trello module) |
| Tavily API key | `TAVILY_API_KEY` | Live E2E (web search module) |
| Codecov token | `CODECOV_TOKEN` | Coverage upload |

---

## 10. Tooling Stack

| Tool | Purpose | Why this choice |
|---|---|---|
| **[pytest](https://docs.pytest.org/)** | Test runner | Already in use. Industry standard for Python. Rich plugin ecosystem. |
| **[pytest-cov](https://pytest-cov.readthedocs.io/)** | Coverage measurement | Native pytest integration. Generates XML for CI. |
| **[pytest-asyncio](https://pytest-asyncio.readthedocs.io/)** | Async test support | Harle uses `async/await` throughout. Simplifies async test writing vs manual `_run()`. |
| **[ruff](https://docs.astral.sh/ruff/)** | Linting + formatting | All-in-one, extremely fast. Replaces flake8 + black + isort. |
| **[mypy](https://mypy.readthedocs.io/)** | Type checking | Catches type errors before runtime. Harle uses type hints extensively. |
| **[DeepEval](https://deepeval.com)** | LLM output evaluation | Pytest-native. Supports relevancy, faithfulness, hallucination metrics. Open-source. |
| **[Promptfoo](https://promptfoo.dev)** | Prompt regression testing | YAML-based, lightweight. Tests prompts independently of application code. |
| **[httpx](https://www.python-httpx.org/)** | API testing | Already a dependency. Works with FastAPI's `TestClient` for integration tests. |
| **[testcontainers](https://testcontainers.com/guides/getting-started-with-testcontainers-for-python/)** | Dockerized test dependencies | Spin up PostgreSQL containers for integration tests. Automatic cleanup. |
| **[pip-audit](https://pypi.org/project/pip-audit/)** | Dependency vulnerability scan | Catches known CVEs in dependencies. Runs in CI. |
| **[Cursor](https://cursor.com)** | AI-assisted test generation & review | Available via subscription. Generates tests, reviews coverage gaps, maintains tests. |

### Updated pyproject.toml test dependencies

```toml
[project.optional-dependencies]
test = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=5.0",
    "httpx>=0.27",
    "deepeval>=2.0",
]
dev = [
    "ruff>=0.8",
    "mypy>=1.13",
    "pip-audit>=2.7",
]
```

---

## 11. Test Data Management

### Fixture vault

Maintain a minimal vault for testing:

```
tests/fixtures/vault/
├── prompts/
│   ├── secretary.md           # Minimal Secretary prompt
│   ├── researcher.md          # Minimal Researcher prompt
│   └── specialist.md          # Minimal Specialist prompt
├── policies/
│   └── tools-allowlist.md     # Test policy
├── workflows/
│   └── task-triage.md         # Test workflow template
├── knowledge/
│   ├── work/
│   │   └── test-note.md       # Known content for search tests
│   └── personal/
│       └── journal.md         # Personal context test
└── tool_skills/
    └── trello/
        └── triage.md          # Override skill for tests
```

### Database fixtures

```python
@pytest.fixture
def db_session(tmp_path):
    """In-memory SQLite for unit tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def pg_session():
    """Real PostgreSQL for integration tests (via testcontainers)."""
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        engine = create_engine(pg.get_connection_url())
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        yield session
        session.close()
```

### Golden dataset maintenance

Golden datasets are JSON files with versioned test cases. When prompts or agent behavior changes:

1. Run the semantic eval suite.
2. Review failures — are they regressions or expected improvements?
3. Update golden dataset entries that reflect intentional changes.
4. Commit updated golden datasets alongside the prompt changes.

---

## 12. Implementation Roadmap

### Phase 1: Foundation (Week 1)

**Goal:** Establish CI/CD infrastructure and linting. No new tests yet — make existing tests run automatically.

| Task | Deliverable |
|---|---|
| Add ruff config to `pyproject.toml` | `[tool.ruff]` section with project-specific rules |
| Add mypy config to `pyproject.toml` | `[tool.mypy]` section |
| Fix any lint/type errors in existing code | Clean `ruff check` and `mypy` output |
| Create `.github/workflows/ci.yml` | Lint + unit tests on every push |
| Add `pytest-cov` and measure baseline coverage | Coverage report showing current state |
| Add pytest markers to `pyproject.toml` | `unit`, `integration`, `semantic`, `e2e` |
| Create `.cursor/rules/test_generation.mdc` | Cursor rule for consistent test generation |

### Phase 2: Coverage Expansion (Week 2)

**Goal:** Fill unit test gaps using Cursor for generation. Target: 70% coverage.

| Task | Deliverable |
|---|---|
| Audit existing tests for coverage gaps | List of untested modules/functions |
| Generate tests for `harle.search.*` module | `test_search_engine.py` expansion |
| Generate tests for `harle.db.*` module | `test_db_operations.py` |
| Generate tests for `harle.api.routes` edge cases | `test_api.py` expansion |
| Generate tests for `harle.indexing.*` | `test_indexer.py` |
| Add `pytest-asyncio` for cleaner async tests | Replace `_run()` helpers |
| Add coverage threshold to CI | Fail PR if coverage drops below 70% |

### Phase 3: Integration Tests (Week 3)

**Goal:** Add integration tests for cross-module flows.

| Task | Deliverable |
|---|---|
| Create fixture vault in `tests/fixtures/vault/` | Minimal vault with known content |
| Add `docker-compose.test.yml` for test PostgreSQL | Test DB container config |
| Write API integration tests with `TestClient` | `test_api_integration.py` |
| Write orchestrator pipeline integration tests | `test_pipeline_integration.py` |
| Write search + context assembly integration test | `test_search_context_integration.py` |
| Add integration tests to PR CI workflow | Separate job with PostgreSQL service |

### Phase 4: Semantic Evaluation (Week 4)

**Goal:** Add LLM output quality testing.

| Task | Deliverable |
|---|---|
| Install and configure DeepEval | `pyproject.toml` dependency, config |
| Create golden dataset for Secretary role | `tests/golden_datasets/secretary_triage.json` |
| Create golden dataset for routing decisions | `tests/golden_datasets/routing_decisions.json` |
| Write semantic eval tests | `tests/test_semantic_eval.py` |
| Configure Promptfoo for prompt regression | `promptfoo/` directory with eval configs |
| Add semantic eval to nightly CI | Scheduled workflow |

### Phase 5: E2E & Go CLI Tests (Week 5)

**Goal:** Full pipeline validation and CLI test coverage.

| Task | Deliverable |
|---|---|
| Write Go unit tests for CLI client | `harle-cli/internal/client/client_test.go` |
| Write Go tests for session manager | `harle-cli/internal/session/manager_test.go` |
| Write Go tests for commands | `harle-cli/internal/commands/*_test.go` |
| Create E2E test harness (emulated mode) | `tests/e2e/` directory |
| Write E2E session lifecycle test | `tests/e2e/test_session.py` |
| Write E2E tool call flow test | `tests/e2e/test_tool_flow.py` |
| Add CLI tests to CI | Go test job in `ci.yml` |
| Add nightly E2E workflow | `nightly.yml` with E2E job |

### Phase 6: Hardening (Week 6)

**Goal:** Polish, documentation, advanced patterns.

| Task | Deliverable |
|---|---|
| Add API contract tests (CLI ↔ Orchestrator) | JSON schema validation tests |
| Add concurrency tests for orchestrator | Parallel request handling |
| Add flaky test detection to CI | `pytest-retry` or failure tracking |
| Add security-focused adversarial tests | Prompt injection, data exfiltration scenarios |
| Raise coverage threshold to 80% | Updated CI config |
| Document testing conventions in this file | Final updates to this document |
| Add pre-commit hooks for local development | `.pre-commit-config.yaml` |

### Phase summary

```
Week 1: CI/CD + linting infrastructure     ← Zero test writing, pure automation
Week 2: Unit test coverage expansion        ← Cursor-assisted test generation
Week 3: Integration tests                   ← Cross-module flow validation
Week 4: Semantic/LLM evaluation             ← AI-specific quality testing
Week 5: E2E + Go CLI tests                  ← Full pipeline + dual codebase
Week 6: Hardening + documentation           ← Security, performance, polish
```

Total estimated effort: **6 weeks** (part-time, single developer). Phases 1–3 are sequential and foundational. Phases 4 and 5 can be partially parallelized. Phase 6 runs continuously alongside later phases.

---

## 13. Metrics & Coverage Targets

### Coverage targets by phase

| Milestone | Unit coverage | Integration coverage | Overall target |
|---|---|---|---|
| **End of Phase 1** | Baseline (measure current) | None | Know where we stand |
| **End of Phase 2** | 70% | None | 70% unit |
| **End of Phase 3** | 75% | Key flows covered | 75% overall |
| **End of Phase 4** | 75% | Key flows + semantic eval | 80% overall |
| **End of Phase 6** | 80% | All critical paths | 85% overall |

### Quality metrics to track

| Metric | Tool | Target |
|---|---|---|
| **Line coverage** | pytest-cov | ≥ 80% |
| **Branch coverage** | pytest-cov | ≥ 70% |
| **Test pass rate** | CI dashboard | 100% on main |
| **Lint/type errors** | ruff + mypy | 0 errors on main |
| **Semantic eval score** | DeepEval | ≥ 0.7 answer relevancy |
| **Faithfulness score** | DeepEval | ≥ 0.8 (no hallucinations) |
| **CI pipeline duration** | GitHub Actions | < 5 min for push, < 15 min for PR |
| **Flaky test rate** | CI logs | < 2% |
| **Dependency vulnerabilities** | pip-audit | 0 critical/high |

### What NOT to measure

- **100% coverage is not a goal.** Diminishing returns make chasing the last 15% more expensive than the value it provides. Focus on covering critical paths, security boundaries, and error handling.
- **LLM output accuracy is a spectrum.** There is no single "correct" answer. Semantic evaluation provides confidence scores, not pass/fail verdicts. Track trends, not absolutes.
- **Speed of individual tests.** Slow tests are acceptable in Layer 3/4. The constraint is total pipeline time, not per-test duration.
