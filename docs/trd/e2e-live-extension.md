---
title: "E2E Live Extension — Real API and Real LLM"
tags: [e2e, testing, live-api, openai, ci, pre-release]
context: global
last_updated: 2026-03-18
summary: "Plan for extending Harle E2E tests to run with real OpenAI (and optionally Tavily, Trello), including CI strategy, secrets, and scenarios."
---

# E2E Live Extension — Real API and Real LLM

> This document is the follow-on plan for **live** end-to-end tests: running the full pipeline with real LLM and real external APIs. Emulated E2E (EchoProvider, local vault) is already implemented; see [Harle Testing Strategy — Current State](../current_state/testing_strategy.md).

---

## Goal

- Run E2E tests with **real OpenAI** (and optionally Tavily, Trello) when corresponding API keys are set.
- Validate tool-call flow, error recovery, and optional security-boundary behaviour in a pre-release or manually triggered pipeline.
- Keep cost and secrets under control; do not run live E2E on every PR.

---

## When to Run

| Trigger | Use case |
|--------|----------|
| **Pre-release** (manual or tag) | Full E2E with real services before cutting a release. |
| **Nightly** (optional) | Run a small subset of live E2E if keys are configured; otherwise skip. |
| **PR / push** | Do **not** run live E2E; keep emulated E2E only. |

---

## CI Strategy

- **Secrets:** Store `OPENAI_API_KEY`, `TAVILY_API_KEY`, `TRELLO_API_KEY`, `TRELLO_API_TOKEN` as repository or environment secrets. Only inject into workflows that are explicitly for pre-release or nightly live E2E.
- **Cost controls:** Limit live E2E to a few scenarios (e.g. one /chat that triggers a tool call, one /chat multi-turn). Use a cheap model (e.g. gpt-4o-mini) and low max_turns where possible.
- **Conditional jobs:** In GitHub Actions, run live E2E only when (a) workflow is `workflow_dispatch` or (b) event is `release` or (c) a specific label is present on the PR. Skip cleanly when secrets are missing.

---

## Scenarios to Add or Enable

1. **Tool call flow:** One or more requests that trigger real tool calls (e.g. dataset_search, search_web) and assert the result incorporates tool output.
2. **Error recovery:** Simulate or trigger an LLM API timeout and assert the API returns a graceful error (e.g. 5xx or structured error message).
3. **Security boundary (optional):** Request that attempts path traversal or unsafe input via a tool; assert the request is rejected or sanitized.

---

## Implementation Notes

- Reuse the same `tests/e2e/` harness and fixtures; add a **live** marker or a separate `tests/e2e/live/` subdirectory for tests that require real API keys. Use `@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="live E2E")` (or a custom marker) so they are skipped when keys are absent.
- Document in [Harle Testing Strategy — Current State](../current_state/testing_strategy.md) when live E2E is implemented and how to run it locally and in CI.
