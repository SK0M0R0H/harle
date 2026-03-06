---
title: "Harle Vault Capture Module — Current State"
tags: [vault-capture, current-state, architecture, implementation-status, onboarding, vault]
context: global
last_updated: 2026-03-06
summary: "Tracks what the Vault Capture Module currently implements, what remains missing relative to the TRD, and what each missing part would unlock."
---

# Harle Vault Capture Module — Current State

> This document compares the target design in the Vault Capture Module TRD with the code that exists today. It focuses on the current implementation in `src/harle/capture` and related database models, and highlights what is implemented, what is only partially implemented, and what is still missing.

Reference TRD: [Vault Capture Module — Architecture & Functionality](../../trd/architecture/vault_capture_module.md)

---

## Overall Status

The Vault Capture Module exists today as an early infrastructure slice, not as a complete user-facing feature. The repository already contains a dedicated `src/harle/capture` package and matching database tables for capture runs, which means the project has started implementing **Phase 1: Core Infrastructure** from the TRD.

What exists is enough to define topics, persist capture run state, and write capture output into the vault. What does **not** exist yet is the runtime system around it: no quick profile flow, no interview engine, no refresh flow, no health checker, no progressive capture hook, no memories bridge, and no CLI or API integration exposing the module to the user.

In practice, the module is currently a **foundation layer** rather than an operational feature.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|---|---|---|
| Topic Registry | Implemented | `src/harle/capture/topics.py` and `src/harle/capture/registry.py` define the topic model and default topic tree. |
| Session / run persistence | Implemented | `src/harle/capture/run.py` and DB models in `src/harle/db/models.py` support create, pause, resume, complete, cancel, and per-topic progress tracking. |
| Profile Writer | Partially implemented | `src/harle/capture/writer.py` writes Markdown with frontmatter and can merge sections, but the merge strategy is simpler than the TRD design. |
| Database schema for capture | Implemented | `capture_runs` and `capture_run_topic_progress` tables exist in SQLAlchemy models and are created by the standard DB initialization path. |
| Quick Profile | Not implemented | No `quick_profile.py`, no CLI questionnaire, no bootstrap trigger. |
| Conversational Interview engine | Not implemented | No `engine.py`, no prompts module, no interview orchestration. |
| Refresh flow | Not implemented | No targeted stale-topic refresh workflow exists. |
| Progressive Capture Hook | Not implemented | No passive capture from normal conversations exists. |
| Health Checker | Not implemented | No staleness, metadata, coverage, or backlog reporting yet. |
| Memories Bridge / consolidation | Not implemented | `memories` table exists, but no bridge or consolidation code is present. |
| CLI integration | Not implemented | No `harle capture ...` or `harle vault check` commands were found. |
| HTTP/API integration | Not implemented | No `/capture` endpoints or equivalent API surface were found. |
| Tests for capture module | Not implemented | No dedicated tests for `harle.capture` were found in `tests/`. |

---

## What Is Implemented

### 1. Topic model and default topic tree

The codebase already includes the TRD's core topic abstractions:

- `Tier`
- `Sensitivity`
- `TopicQuestion`
- `Topic`

The default topic tree in `src/harle/capture/topics.py` covers the same major areas described in the TRD:

- Tier 1 work topics
- Tier 2 work topics
- Tier 3 personal topics
- Tier 4 goals / aspirational topics

This is a strong match with the intended architecture. The current implementation already treats the topic registry as **data-driven**, which aligns well with the TRD's main design principle for this component.

### 2. Topic querying via `TopicRegistry`

`src/harle/capture/registry.py` provides query methods for:

- all topics
- topic lookup by id
- filtering by tier
- filtering by scope
- detecting stale topics from completion timestamps

That means the system already has the core read/query behavior needed by future capture flows, health checks, and refresh logic.

### 3. Capture run lifecycle persistence

The TRD's Session Manager has been implemented under a slightly different naming scheme:

- TRD term: `Session Manager`
- current code term: `CaptureRunManager`
- TRD term: `CaptureSession`
- current code term: `CaptureRun`

This naming change is documented in code comments and appears intentional, mainly to avoid confusion with chat sessions.

The current implementation supports:

- creating a run
- selecting topics for the run based on scope and tier
- starting a run
- pausing a run
- resuming a run
- completing a run
- cancelling a run
- updating per-topic progress, answers, generated content, and vault path

The matching SQLAlchemy tables also exist:

- `capture_runs`
- `capture_run_topic_progress`

This gives the project a real persistence backbone for resumable capture workflows.

### 4. Basic vault writing with frontmatter

`ProfileWriter` can already:

- validate that writes stay inside the vault root
- create parent directories
- generate frontmatter for new files
- update `last_updated` when writing an update
- merge new content into an existing document by section heading

This is enough to support basic generated vault output and gives the project a reusable write path for later capture flows.

### 5. Capture package export surface

`src/harle/capture/__init__.py` exposes the main Phase 1 objects as a coherent module API. That is a small but useful sign that the code was written as a real subsystem rather than as isolated experiments.

---

## What Is Only Partially Implemented

### Profile Writer merge behavior

The TRD describes a sophisticated merge strategy that preserves user-edited sections and appends capture updates when needed. The current implementation does **not** do that yet.

Current behavior:

- split existing and new documents by heading
- replace matching headings
- append new headings that do not exist yet

Missing behavior from the TRD:

- detection of user-modified sections
- preservation of manual edits when capture data changes
- append-only fallback such as a `[Capture update]` subsection

This means the current writer is useful for bootstrapping, but it is not yet safe enough for the full refresh workflow described in the TRD.

### Database readiness vs. product readiness

The database schema exists, but the user-facing workflows that would populate and consume it do not. The tables are present because they are part of the global ORM model set, not because the full capture product is already active.

This is an important distinction: the module is **schema-ready**, but not yet **flow-ready**.

---

## What Is Not Implemented Yet

### 1. Quick Profile flow

Missing pieces:

- `quick_profile.py`
- CLI questionnaire
- bootstrap trigger for empty vaults
- response-to-document generation flow

What this would unlock:

- the first usable onboarding experience for new users
- immediate creation of a minimal personalized vault
- a practical path to fulfill the TRD rule of "never present a blank canvas"

### 2. Conversational interview engine

Missing pieces:

- `engine.py`
- interview prompt templates
- topic-cluster orchestration
- adaptive follow-up questions
- user confirmation loop around generated drafts

What this would unlock:

- the main high-value capture workflow described in the TRD
- deeper user modeling beyond a short bootstrap form
- progressive depth in onboarding rather than one-shot static input

### 3. Refresh workflow

Missing pieces:

- stale-topic loading
- display of current vault content before re-capture
- targeted update flow for existing files
- refresh-specific orchestration rules

What this would unlock:

- keeping personalized knowledge current over time
- safe re-interview on aging facts such as projects, tools, and preferences
- a practical maintenance loop rather than one-time onboarding only

### 4. Health Checker

Missing pieces:

- staleness detection across vault files
- metadata validation for capture outputs
- coverage analysis against the topic registry
- progressive-capture backlog reporting
- human-readable health report generation

What this would unlock:

- visibility into how complete and how stale the user's vault is
- a clear mechanism to recommend next capture actions
- the basis for proactive nudges such as "refresh this topic" or "fill this gap"

### 5. Progressive Capture Hook

Missing pieces:

- interception of normal conversations
- preference/fact extraction rules
- confidence-based filtering
- exclusions for sensitive topics
- background save path for durable preferences

What this would unlock:

- learning from normal usage without forcing explicit onboarding
- gradual personalization over time
- a more natural UX where Harle becomes more useful as the user works

### 6. Memories Bridge and consolidation

Missing pieces:

- extraction of atomic memories from capture outputs
- synchronization from vault documents into `memories`
- consolidation of progressively captured facts back into structured documents

What this would unlock:

- the bridge between human-readable vault files and fast machine-queryable facts
- immediate personalization from newly captured knowledge
- consolidation of fragmented learned preferences into stable documents

### 7. CLI and API integration

Missing pieces:

- `harle capture quick`
- `harle capture interview`
- `harle capture refresh`
- `harle capture consolidate`
- `harle capture status`
- `harle vault check`
- API endpoints for capture lifecycle and interaction

What this would unlock:

- actual access to the module from the product
- manual and automated entry points for onboarding and refresh
- a path for future UI layers to call the same workflows

### 8. Re-indexing and post-write side effects

Missing pieces:

- immediate re-index trigger after capture writes
- automatic updates to related memory records
- completion bookkeeping coupled to successful writes

What this would unlock:

- "immediate value" after capture, as described in the TRD
- newly captured knowledge becoming searchable right away
- more reliable synchronization across the vault, DB, and future reasoning pipeline

### 9. Tests for the module

Missing pieces:

- unit tests for topic registry behavior
- unit tests for run lifecycle persistence
- unit tests for writer merge behavior

What this would unlock:

- confidence to evolve the module without breaking pause/resume or vault writes
- safer implementation of later phases like refresh and progressive capture
- faster iteration on prompt-driven flows once the engine is added

---

## Key Deviations From The TRD

### "Session" became "Run"

The code uses `CaptureRun` and `CaptureRunManager` rather than `CaptureSession` and `Session Manager`. This is not a problem by itself, but future documentation should stay explicit about the terminology so chat sessions and capture workflows are not confused.

### Implementation path differs from the issue shorthand

The active implementation is in `src/harle/capture`, not `src/capture`. Any future current-state docs or rules should point to the real package path.

### Phase 1 is narrower than the TRD promise

The TRD's Phase 1 description includes verification and a full working foundation for later phases. The repository currently has the production code skeleton for that phase, but it is not yet backed by module-specific tests or integrated product flows.

### Writer safety is below the TRD target

The existing merge strategy is appropriate for a first pass, but it does not yet satisfy the TRD promise that user edits are preserved intelligently during updates.

---

## Current Assessment

The Vault Capture Module is **started well but still pre-feature**.

The strongest implemented parts are:

- the topic system
- persistent capture run data structures
- the basic vault writer

The most important missing parts are:

- user-facing entry points
- the actual conversational engine
- health and refresh loops
- synchronization with memories and indexing

The next meaningful milestone would be to turn the current infrastructure into the first end-to-end flow, most likely **Quick Profile**, because that would convert the existing foundation into something the user can actually run and benefit from.
