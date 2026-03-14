---
title: "Harle Vault Capture Module — Current State"
tags: [vault-capture, current-state, architecture, implementation-status, onboarding, vault]
context: global
last_updated: 2026-03-13
summary: "Tracks what the Vault Capture Module currently implements, what remains missing relative to the TRD, and what each missing part would unlock."
---

# Harle Vault Capture Module — Current State

> This document compares the target design in the Vault Capture Module TRD with the code that exists today. It focuses on the current implementation in `src/harle/capture` and related database models, and highlights what is implemented, what is only partially implemented, and what is still missing.

Reference TRD: [Vault Capture Module — Architecture & Functionality](../../trd/architecture/vault_capture_module.md)

---

## Overall Status

The Vault Capture Module now includes both the **Phase 1: Core Infrastructure** and the **Phase 4: Conversational Interview** from the TRD. The module provides a complete topic registry, run lifecycle management, a profile writer, and a fully functional interview engine with LLM-driven adaptive questions, document draft generation, and an interactive CLI flow.

The module is now an **operational feature** that users can invoke through `harle capture interview`.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|---|---|---|
| Topic Registry | Implemented | `topics.py` and `registry.py` define the topic model and default topic tree. |
| Session / run persistence | Implemented | `run.py` and DB models support create, pause, resume, complete, cancel, find-resumable, and per-topic progress. |
| Profile Writer | Partially implemented | `writer.py` writes Markdown with frontmatter and can merge sections; merge strategy is simpler than TRD design (no user-edit detection). |
| Database schema for capture | Implemented | `capture_runs` and `capture_run_topic_progress` tables in SQLAlchemy models. |
| Quick Profile | Not implemented | No `quick_profile.py`, no CLI questionnaire, no bootstrap trigger. |
| Conversational Interview engine | Implemented | `engine.py` + `interview_helpers.py` + `prompts.py` provide full interview flow with topic-cluster orchestration, adaptive LLM follow-ups, summary/confirmation, draft generation, and user approval loop. |
| Interview prompt templates | Implemented | `prompts.py` includes system prompt, question builder, summary builder, draft builder, and per-topic capability notes. |
| Refresh flow | Not implemented | No targeted stale-topic refresh workflow. |
| Progressive Capture Hook | Not implemented | No passive capture from normal conversations. |
| Health Checker | Not implemented | No staleness, metadata, coverage, or backlog reporting. |
| Memories Bridge / consolidation | Not implemented | `memories` table exists, but no bridge or consolidation code. |
| CLI integration (Go) | Partially implemented | `harle capture interview` subcommand with `--scope`, `--tier`, `--resume` flags. Other capture commands (`quick`, `refresh`, `consolidate`, `status`) and `harle vault check` not implemented. |
| HTTP/API integration | Partially implemented | `/capture/interview/start` and `/capture/interview/respond` endpoints. No `/capture/status` or `/vault/check`. |
| Tests for capture module | Not implemented | No dedicated tests for `harle.capture` were found in `tests/`. |

---

## What Is Implemented

### 1. Topic model and default topic tree

The full TRD topic tree is implemented with `Tier`, `Sensitivity`, `TopicQuestion`, `Topic` dataclasses and the `default_topic_tree()` function covering tiers 1–4 (work, personal, goals).

### 2. Topic querying via `TopicRegistry`

`registry.py` provides query methods for all topics, by ID, by tier, by scope, and stale topic detection. The `TopicSelector` helper in `interview_helpers.py` provides topic ordering and next-topic selection.

### 3. Capture run lifecycle persistence

`CaptureRunManager` supports: create, start, pause, resume, complete, cancel, find-resumable, and per-topic progress updates. All state is persisted in PostgreSQL via `capture_runs` and `capture_run_topic_progress` tables.

### 4. Profile Writer with merge

`ProfileWriter` writes capture outputs to vault with YAML frontmatter, creates directories, and merges by section heading on updates.

### 5. Conversational Interview Engine (Phase 4)

The interview engine (`engine.py`, `interview_helpers.py`, `prompts.py`) provides:

- **State machine per topic cluster**: questioning → summary/confirmation → draft review → approval → vault write
- **LLM-driven adaptive questions**: uses the OpenAI API to rephrase registry questions naturally and generate follow-ups based on user answers
- **GATE methodology**: open-ended questions, progressive depth (broad → narrow)
- **Summary and confirmation**: after 3–5 questions per cluster, generates a summary and asks "did I miss anything?"
- **Vault document generation**: LLM generates Markdown documents (not Q&A transcripts) from collected answers
- **Draft review flow**: user can approve, edit, or skip each draft
- **Tier breaks**: after each tier, offers a stopping point (DP-6)
- **Privacy handling**: high-sensitivity topics include a privacy note (DP-7)
- **Capability notes**: after each topic, explains what the captured knowledge enables (DP-4)
- **Pause/resume**: sessions persist to DB and can be resumed later
- **Fallback mode**: when no OpenAI API key is set, uses registry questions directly and simple text templates

### 6. HTTP API for interview

- `POST /capture/interview/start` — start or resume an interview session
- `POST /capture/interview/respond` — process user responses and advance the interview

### 7. Go CLI for interview

- `harle capture interview` — interactive interview loop
- Flags: `--scope`, `--tier`, `--resume`
- Slash commands: `/pause`, `/skip`, `/quit`
- Draft review: `y` to approve, type to edit, `/skip` to skip

---

## What Is Only Partially Implemented

### Profile Writer merge behavior

Current behavior: replace matching headings, append new headings. Missing: detection of user-modified sections, preservation of manual edits, append-only `[Capture update]` fallback.

### CLI coverage

Only `harle capture interview` is implemented. Missing: `harle capture quick`, `harle capture refresh`, `harle capture consolidate`, `harle capture status`, `harle vault check`.

### API coverage

Only interview start/respond endpoints. Missing: status endpoint, vault check endpoint.

---

## What Is Not Implemented Yet

### 1. Quick Profile flow

No `quick_profile.py`, CLI questionnaire, or bootstrap trigger. Would provide a 5-minute no-LLM onboarding path.

### 2. Refresh workflow

No targeted stale-topic refresh. Would keep personalized knowledge current over time.

### 3. Health Checker

No staleness, metadata, coverage analysis, or health reports. Would provide vault quality visibility.

### 4. Progressive Capture Hook

No passive preference capture from normal conversations. Would enable organic learning.

### 5. Memories Bridge and consolidation

No vault ↔ memories sync, no progressive capture consolidation. Would bridge human-readable files and machine-queryable facts.

### 6. Re-indexing and post-write side effects

No automatic re-index trigger after writes. Would make captured knowledge immediately searchable.

### 7. Tests for the module

No dedicated unit or integration tests. Would enable safe evolution of the module.

---

## Key Deviations From The TRD

### "Session" became "Run"

The code uses `CaptureRun` and `CaptureRunManager` to avoid confusion with chat sessions.

### Interview uses direct OpenAI calls, not the Orchestrator's conversation mode

The TRD says the interview should reuse the Orchestrator's conversation mode. The current implementation uses the OpenAI API directly from the CaptureEngine, with its own prompt construction. This avoids coupling to the orchestrator's multi-turn infrastructure and gives the interview engine full control over the LLM interaction, but means conversation history is stored in the capture run (answers JSON), not in the conversations/messages tables.

### Summary and draft generation are combined

The TRD describes separate "summarize and confirm" and "generate draft" steps. The current implementation generates both in one transition, showing the summary as a preamble to the draft.

---

## Current Assessment

The Vault Capture Module is now a **working feature** for the primary use case: conversational interviews that capture personal knowledge into vault documents. The interview flow follows the TRD's topic tree, interview techniques, and design principles (DP-1, DP-2, DP-4, DP-5, DP-6, DP-7).

The most impactful next steps are:

1. **Quick Profile** — provides a no-LLM fallback for fast onboarding
2. **Health Checker** — enables vault quality monitoring
3. **Tests** — enables confident evolution of the module
4. **Re-indexing** — makes captured knowledge immediately searchable
