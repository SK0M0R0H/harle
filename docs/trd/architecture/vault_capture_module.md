---
title: "Harle Vault Capture Module — Architecture & Functionality"
tags: [vault-capture, architecture, onboarding, interview, progressive-capture, vault-health, knowledge-capture, ux]
context: global
last_updated: 2026-03-01
summary: "Describes the Vault Capture Module's architecture: how personal knowledge is captured via interviews, quick profiles, and progressive learning; how vault health is monitored and stale content refreshed; and how UX principles guide every interaction."
---

# Harle Vault Capture Module — Architecture & Functionality

> The Vault Capture Module is how personal knowledge enters Harle's vault from the user's head. Every time the system interviews the user, refreshes stale preferences, detects knowledge gaps, or learns something new from a normal conversation, the work goes through this module. It makes knowledge capture structured, resumable, and non-intrusive — whether triggered during onboarding, on a schedule, or organically during use.

This document describes the Vault Capture Module's internal architecture: how topic trees define what to capture, how capture sessions manage the conversational flow, how vault health monitoring identifies staleness and gaps, and how the module connects to the Orchestrator, CLI, and the rest of the system.

For the overall system architecture, see [overview.md](./overview.md).
For the vault structure and file conventions, see [data.md](./data.md).
For the import module (external data migration), see [import_module.md](./import_module.md).
For the research behind this design, see [vault_ux_onboarding.md](../../research/vault_ux_onboarding.md), Sections 3, 4, and 7.

---

## Why a Separate Module (Not Part of Import or Tools)

The Import Module Layer handles **external data migration** — Notion pages, Miro boards, bookmarks. The Tool Module Layer handles **runtime tool calls** during agent reasoning. Vault capture is a different concern:

| Import Modules | Tool Modules | Vault Capture Module |
|---|---|---|
| Extract from external systems | Called during agent reasoning | Elicit knowledge from the user's head |
| Input: files, APIs, exports | Input: agent tool calls | Input: conversational answers, form responses |
| One-directional (system → vault) | Ephemeral (read/write external services) | Bidirectional (ask user → generate → user refines → save) |
| Deterministic conversion | Single API calls, fast | Multi-turn LLM conversations, variable length |
| Runs once or periodically per source | Runs per agent request | Runs during onboarding, refresh cycles, and ongoing use |

Vault capture requires its own session management (pause/resume interviews across days), topic tracking (which areas of personal knowledge are covered vs. missing), health monitoring (staleness, completeness), and integration with the memories system. None of these concerns belong in the import pipeline or tool registry.

---

## Where the Vault Capture Module Sits

```
                        ┌──────────────────────────────────────────────────┐
                        │              ORCHESTRATOR                        │
                        │                                                  │
                        │  ┌──────────┐   ┌──────────┐   ┌─────────────┐  │
                        │  │ HTTP API │   │ CLI      │   │ Agent Runner│  │
                        │  └────┬─────┘   └────┬─────┘   └──────┬──────┘  │
                        │       │              │                │         │
                        │       │         ┌────▼────────────────▼──────┐  │
                        │       │         │    Vault Capture Module    │  │
                        │       │         └──────────────┬─────────────┘  │
                        │       │                        │                │
                        └───────┼────────────────────────┼────────────────┘
                                │                        │
                    ┌───────────┼────────────────────────┼────────────────────┐
                    │           │   VAULT CAPTURE MODULE                      │
                    │           │                                             │
                    │  ┌────────▼──────────────────────────────────────────┐  │
                    │  │              Capture Engine                       │  │
                    │  │                                                   │  │
                    │  │  ┌──────────┐ ┌──────────┐ ┌───────────────────┐  │  │
                    │  │  │ Topic    │ │ Session  │ │ Progressive       │  │  │
                    │  │  │ Registry │ │ Manager  │ │ Capture Hook      │  │  │
                    │  │  └────┬─────┘ └────┬─────┘ └────────┬──────────┘  │  │
                    │  └───────┼────────────┼─────────────────┼────────────┘  │
                    │          │            │                 │               │
                    │     ┌────▼────┐  ┌────▼────┐     ┌─────▼─────┐        │
                    │     │ Health  │  │ Profile │     │ Memories  │        │
                    │     │ Checker │  │ Writer  │     │ Bridge    │        │
                    │     └─────────┘  └────┬────┘     └───────────┘        │
                    │                       │                                │
                    │                       ▼                                │
                    │               ┌──────────────┐                        │
                    │               │  Vault (files)│                        │
                    │               └──────────────┘                        │
                    └───────────────────────────────────────────────────────┘
```

The Vault Capture Module is an internal part of the Orchestrator process. It provides six components:

1. **Topic Registry** — defines and organizes what personal knowledge can be captured, in a hierarchical topic tree.
2. **Session Manager** — manages the lifecycle of capture sessions: creation, pause, resume, completion.
3. **Progressive Capture Hook** — intercepts normal conversations to detect and save new preferences.
4. **Health Checker** — analyzes vault content for staleness, missing metadata, and knowledge gaps.
5. **Profile Writer** — writes capture results to the vault as properly formatted Markdown.
6. **Memories Bridge** — synchronizes captured knowledge with the `memories` database table.

---

## Not a One-Time Setup

Capture is **not** an onboarding-only operation. Users' lives, roles, preferences, and goals evolve. The module runs across the entire lifecycle:

| Scenario | When capture runs | Mode |
|---|---|---|
| First-time onboarding | `harle init` or first interaction | Quick profile + interview |
| Deeper onboarding | User runs `harle capture interview` after initial setup | Full interview |
| Stale content refresh | `harle capture refresh` or proactive suggestion from Harle | Targeted re-interview on stale topics |
| New role or project | User starts a new job, project, or life phase | Scoped interview (work context only) |
| Progressive learning | During any normal conversation | Automatic — hook detects new preferences |
| Vault health check | `harle vault check` or scheduled | Health report with suggestions |
| Periodic consolidation | Weekly/monthly prompt from Harle | Review and organize accumulated progressive captures |

The module must support **resumable sessions** (user does Tier 1 today, Tier 2 next week), **scoped capture** (refresh only work-related topics), **idempotent runs** (re-interviewing on a topic updates the existing document rather than creating duplicates), and **progressive accumulation** (preferences learned organically are stored and periodically consolidated).

---

## Design Principles

These principles — drawn from the UX research in Section 7 of the research document — are not guidelines; they are **design constraints** that every component in this module must satisfy.

### DP-1: Never Present a Blank Canvas

Every interaction that produces vault content must generate **meaningful defaults**. The user never sees an empty file. Even the most minimal capture (a name and a role) produces a vault document with content. The difference between "0 files" and "3 files with basic information" is the difference between a useless tool and one that is starting to learn.

**How this constrains the design:**
- Quick profile mode always produces at least 2 vault files, even from minimal answers.
- Interview mode shows a generated draft after each topic cluster — not at the end.
- Refresh mode pre-fills current vault content and asks the user to confirm, correct, or extend — never starts from nothing.

### DP-2: Generate First, Refine Later

The AI writes the first draft. The user edits, approves, or discards. This inverts the "user writes, AI reads" model.

**How this constrains the design:**
- After the user answers 3–5 questions, the Capture Engine generates a full Markdown document — not a list of raw answers.
- The generated document includes proper frontmatter, structured sections, and natural language — not a Q&A transcript.
- The user's only required action is approval (`y`) or edit. They never have to write from scratch.

### DP-3: Show Immediate Value

Within 5 minutes of completing any capture session, the user should be able to ask Harle a question and get a response that demonstrates personalization. If the user told Harle their Trello board name, the next Trello query should use it without asking.

**How this constrains the design:**
- Profile Writer triggers an immediate re-index of written files so the Search Algorithm includes new content.
- Memories Bridge writes high-confidence memories for actionable facts (tool names, board IDs, preferred formats) immediately, without waiting for consolidation.
- The module optionally suggests a "test query" after capture: "Try asking me 'What should I focus on this week?' to see how I use what you just told me."

### DP-4: Make Effort Feel Proportional

Each question asked during capture must visibly improve Harle's responses. The user should perceive a direct link between their input and the system's competence.

**How this constrains the design:**
- After each topic cluster, the Capture Engine reports what new capability this enables: "Now that I know your Trello board, I can find stalled tasks without asking you which board to check."
- The Health Checker's completeness score is framed in terms of capabilities, not percentages: "Adding travel preferences would let me plan trips without asking 5 setup questions each time."

### DP-5: Respect "I'll Do It Later"

Every capture step must be skippable. Users who skip should still get a functional experience. The module periodically and non-intrusively reminds them about skipped topics.

**How this constrains the design:**
- Session Manager tracks skipped topics separately from uncovered topics.
- Skipped topics surface as low-priority suggestions during vault health checks: "You skipped travel preferences last time. Want to spend 2 minutes on that?"
- Skipping never blocks progress — the session continues to the next topic.

### DP-6: Progressive Profiling Over Interrogation

Spreading data collection across touchpoints feels conversational rather than interrogative. Capture 5 facts today, 5 next week, 5 the week after — never 50 at once.

**How this constrains the design:**
- Interview sessions are tiered. Each tier is a self-contained unit (5–10 minutes). Completing Tier 1 is valuable on its own; Tier 2 adds depth; Tiers 3–4 are optional.
- The Progressive Capture Hook accumulates preferences organically from normal use.
- Periodic consolidation merges progressive captures into structured vault documents.
- The module never asks more than 10 questions in a single session without offering a stopping point.

### DP-7: Privacy as a Feature

When asking for personal information (health, finances, goals), the module frames privacy controls as empowering, not alarming.

**How this constrains the design:**
- Topics involving sensitive data (health, finances) are explicitly marked as optional and include a privacy note: "This stays in your vault on your machine — I never send it anywhere."
- The Topic Registry tags topics with a sensitivity level. High-sensitivity topics are never asked during progressive capture — only during explicit interview sessions where the user has opted in.
- Health-related vault files are placed in `knowledge/personal/health/` with a `context: personal` tag, ensuring they are excluded from work-scoped queries.

---

## Internal Components

### 1. Topic Registry (what to capture)

**What it does:** Defines the universe of personal knowledge that the module can capture. Topics are organized in a hierarchical tree with tiers, categories, and individual questions.

**Key design principle:** The Topic Registry is data, not code. Topics are defined declaratively so they can be extended without changing the capture engine. New topics mean new entries in the registry — nothing else changes.

```python
from dataclasses import dataclass, field
from enum import Enum


class Tier(Enum):
    """Capture urgency / importance level."""
    ESSENTIAL = 1
    USEFUL = 2
    PERSONAL = 3
    ASPIRATIONAL = 4


class Sensitivity(Enum):
    """Privacy sensitivity of the topic."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class TopicQuestion:
    """A single question within a topic."""
    id: str
    prompt: str
    follow_ups: list[str] = field(default_factory=list)
    example_answer: str = ""
    input_type: str = "open"


@dataclass
class Topic:
    """A capturable topic with questions and metadata."""
    id: str
    name: str
    description: str
    tier: Tier
    category: str
    context: str
    sensitivity: Sensitivity
    questions: list[TopicQuestion]
    vault_target: str
    depends_on: list[str] = field(default_factory=list)
    refresh_interval_days: int = 90
```

**Topic tree (first version):**

```
Work Context (Tier 1 — Essential, ~5 min)
├── role_and_team
│   ├── "What is your job title and role?"
│   ├── "What team or department are you part of?"
│   └── follow-up: "Do you manage people or report to someone specific?"
├── current_projects
│   ├── "What are you working on right now? (1-3 projects)"
│   └── follow-up: "For each project, what tools do you use to track it?"
├── daily_tools
│   ├── "What tools do you use every day for work?"
│   └── follow-up: "Do any of these have specific board/workspace names I should know?"
└── communication_style
    ├── "How do you prefer information delivered? (bullets, paragraphs, tables)"
    └── follow-up: "Should status updates be brief or detailed?"

Work Context (Tier 2 — Useful, ~10 min)
├── recurring_decisions
│   ├── "What decisions do you make regularly at work?"
│   └── follow-up: "Are there criteria you use each time?"
├── pain_points
│   ├── "What wastes your time most at work?"
│   └── follow-up: "Is there a task you wish someone else handled?"
├── reporting_preferences
│   ├── "When you receive reports, what must be included?"
│   └── follow-up: "Are there formats or lengths you prefer?"
└── work_hours_timezone
    ├── "What time zone are you in?"
    └── "Do you have set work hours or a flexible schedule?"

Personal Context (Tier 3 — Personal, ~10 min)
├── dietary_preferences [sensitivity: medium]
│   ├── "Do you have dietary preferences or restrictions?"
│   └── follow-up: "Favorite cuisines or restaurants?"
├── travel_preferences [sensitivity: medium]
│   ├── "Do you travel often?"
│   ├── "Window or aisle? Hotel preferences?"
│   └── follow-up: "Budget range for travel?"
├── health_notes [sensitivity: high]
│   ├── "Any health conditions I should know about? (completely optional)"
│   └── privacy note: "This stays in your vault on your machine."
└── communication_preferences
    ├── "Do you prefer formal or casual tone from me?"
    └── follow-up: "Any communication habits I should match?"

Goals & Interests (Tier 4 — Aspirational, ~10 min)
├── short_term_goals
│   ├── "What are your goals for the next 1-3 months?"
│   └── follow-up: "What would 'done' look like for each?"
├── long_term_goals
│   ├── "What are your goals for this year or beyond?"
│   └── follow-up: "Are there milestones along the way?"
├── learning_interests
│   ├── "What topics do you want to learn about?"
│   └── follow-up: "Books, courses, or hands-on projects?"
└── areas_of_expertise
    ├── "What topics do you consider yourself an expert in?"
    └── follow-up: "Would you like me to use technical vocabulary in those areas?"
```

**Where information lives (no duplication):**

| What | Where it lives | Who reads it |
|---|---|---|
| Topic definitions (questions, tiers, categories) | Topic Registry (in code, loaded at startup) | Capture Engine, Health Checker |
| Topic coverage status (which topics were captured, when) | `capture_sessions` DB table | Session Manager, Health Checker |
| Captured content (user's actual answers, generated documents) | Vault files + `memories` DB table | Search Algorithm, Context Assembler |
| Topic sensitivity levels | Topic Registry metadata | Capture Engine (filters sensitive topics from progressive capture) |
| Refresh intervals per topic | Topic Registry metadata | Health Checker (determines staleness) |

---

### 2. Session Manager (manage capture lifecycle)

**What it does:** Creates, tracks, pauses, resumes, and completes capture sessions. A session is a single capture interaction — it may cover one tier or many, span minutes or days, and be triggered manually or by the system.

**Key design principle:** Sessions are resumable. A user who completes Tier 1 on Monday and returns on Thursday for Tier 2 picks up exactly where they left off. The system never re-asks questions that were already answered (unless explicitly in refresh mode).

```python
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class SessionMode(Enum):
    """How the capture session operates."""
    QUICK_PROFILE = "quick_profile"
    INTERVIEW = "interview"
    REFRESH = "refresh"
    PROGRESSIVE = "progressive"


class SessionState(Enum):
    """Lifecycle state of a capture session."""
    CREATED = "created"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class TopicProgress:
    """Tracks capture progress for a single topic."""
    topic_id: str
    status: str  # "pending", "in_progress", "completed", "skipped"
    answers: dict = field(default_factory=dict)
    generated_content: str = ""
    vault_path: str = ""
    completed_at: datetime | None = None


@dataclass
class CaptureSession:
    """A capture interaction spanning one or more topics."""
    session_id: str
    mode: SessionMode
    state: SessionState
    scope: str  # "all", "work", "personal", "goals"
    target_tiers: list[int]
    topic_progress: dict[str, TopicProgress]
    conversation_id: str | None = None
    created_at: datetime = field(
        default_factory=datetime.utcnow
    )
    updated_at: datetime = field(
        default_factory=datetime.utcnow
    )
    completed_at: datetime | None = None
```

**Session lifecycle:**

```
            ┌─────────────────────┐
            │     CREATED         │
            │  Session initialized│
            │  Topics selected    │
            └──────────┬──────────┘
                       │
                       │  User starts session
                       ▼
            ┌─────────────────────┐
            │      ACTIVE         │◄──────────────────┐
            │  Questions asked    │                    │
            │  Answers collected  │                    │
            │  Docs generated     │                    │
            └────┬───────────┬────┘                    │
                 │           │                         │
    User says    │           │  All target topics      │
    "pause" or   │           │  completed              │
    session      │           │                         │
    times out    │           ▼                         │
                 │  ┌─────────────────────┐            │
                 │  │    COMPLETED        │            │
                 │  │  Summary displayed  │            │
                 │  │  Files written      │            │
                 │  │  Re-index triggered │            │
                 │  └─────────────────────┘            │
                 │                                     │
                 ▼                                     │
            ┌─────────────────────┐                    │
            │      PAUSED         │                    │
            │  Progress saved     │    User resumes    │
            │  Can resume later   │────────────────────┘
            └─────────────────────┘
```

**Database schema for session persistence:**

```sql
CREATE TABLE capture_sessions (
    id              SERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL UNIQUE,
    mode            TEXT NOT NULL,
    state           TEXT NOT NULL,
    scope           TEXT NOT NULL,
    target_tiers    INTEGER[],
    conversation_id TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMP
);

CREATE TABLE capture_topic_progress (
    id              SERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES capture_sessions(session_id),
    topic_id        TEXT NOT NULL,
    status          TEXT NOT NULL,
    answers         JSONB DEFAULT '{}',
    generated_content TEXT,
    vault_path      TEXT,
    completed_at    TIMESTAMP,
    UNIQUE(session_id, topic_id)
);
```

**Why session persistence in the database (not just conversation history):**
- Conversations can be summarized or truncated to fit context windows. Session progress must be precise — "topic X was completed, topic Y was skipped" cannot be inferred from a compressed summary.
- Resume after days or weeks. Conversation context may be stale; session state is not.
- The Health Checker queries session history to determine coverage and staleness without replaying conversations.

---

### 3. Capture Engine (orchestrate the conversation)

**What it does:** The Capture Engine is the brain of the module. It selects topics, formulates questions, processes answers, generates vault documents, and manages the flow of each session mode. It uses an LLM for conversational adaptation and document generation, but the session logic is deterministic.

**Session modes in detail:**

#### Mode A: Quick Profile (5 minutes, no LLM dependency)

The minimum viable capture. A structured form that asks 7–10 essential questions and generates 2–3 vault documents. Implemented in the CLI with no conversation mode required.

```
=== Harle Quick Profile (5 minutes) ===

1. What is your name? _______________
2. What do you do for work? (1-2 sentences) _______________
3. What tools do you use daily? (comma-separated) _______________
4. How do you prefer information delivered?
   [ ] Bullet points  [ ] Paragraphs  [ ] Tables  [ ] Depends
5. What are you working on right now? (1-2 projects) _______________
6. What time zone are you in? _______________
7. Do you have dietary restrictions? (optional) _______________
8. Top 3 goals this year? (optional)
   1. _______________
   2. _______________
   3. _______________
```

**Output:** 2–3 vault files generated from responses:
- `knowledge/work/profile.md` — role, projects, tools, communication style
- `knowledge/personal/preferences.md` — dietary, format preferences
- `knowledge/personal/goals.md` — goals (if provided)

Quick profile follows DP-1 (never blank canvas) — even if the user answers only questions 1–3, two vault files are generated.

#### Mode B: Conversational Interview (10–30 minutes, LLM-driven)

The core capture experience. A multi-turn conversation where the Capture Engine interviews the user using the topic tree, adapts follow-ups based on responses, and generates vault documents after each topic cluster.

**How it works:**

```
1. Session Manager creates a session with target tiers
2. Capture Engine selects the first topic cluster
3. For each topic cluster:
   a. Ask the first question (open-ended, per GATE methodology)
   b. Listen to the answer
   c. Generate 1-2 adaptive follow-ups based on the answer
      (progressive depth: broad → narrow)
   d. After 3-5 questions, summarize and confirm:
      "Here's what I captured — did I miss anything?"
      (reflection and confirmation)
   e. Generate a vault document draft and show it to the user
   f. User approves, edits, or skips
   g. Profile Writer saves the approved document
   h. Move to the next topic cluster

4. After each tier, offer a stopping point:
   "We've covered the basics. Want to continue with
    [next tier] or stop here for today?"

5. Session completes or pauses based on user choice
```

**Interview techniques (built into the Capture Engine's prompt):**

| Technique | What it does | Where it applies |
|---|---|---|
| **GATE (Generative Active Task Elicitation)** | Use open-ended questions rather than multiple-choice. "Tell me about your typical workday" surfaces more than "Do you use Slack? (yes/no)" | All interview questions |
| **Progressive depth** | Start broad, then narrow based on responses. "What tools do you use?" → "You mentioned Trello — do you have a specific board for work?" | Follow-up generation |
| **Reflection and confirmation** | After 3–5 questions, summarize and ask "Did I miss anything?" | End of each topic cluster |
| **Latent preference discovery** | Ask follow-ups that surface hidden preferences. "You said bullets — for all documents or just status reports?" | Adaptive follow-ups |

**LLM prompt structure for interview mode:**

The Capture Engine constructs a prompt that includes:
1. The capture agent identity ("You are conducting an interview to learn about the user")
2. The current topic cluster's questions (from Topic Registry)
3. Session history (what has been captured so far in this session)
4. Instructions for generating vault documents (format, frontmatter, structure)
5. Constraints: DP-2 (generate first), DP-6 (max 10 questions before offering a break)

The Capture Engine reuses the Orchestrator's existing conversation mode infrastructure — the interview is a conversation with a specialized agent prompt, not a separate system.

#### Mode C: Refresh (targeted, variable length)

Re-visits specific topics that are stale or incomplete. The Capture Engine loads existing vault content for the topic, presents it to the user, and asks for updates.

**How it works:**

```
1. Health Checker identifies stale or incomplete topics
2. Capture Engine loads existing vault document for each topic
3. For each stale topic:
   a. Show current content: "Here's what I have for your
      current projects (last updated 4 months ago)"
   b. Ask: "Is this still accurate? What changed?"
   c. User provides updates
   d. Generate an updated document (merge, not replace)
   e. User approves → Profile Writer updates the file

4. For incomplete topics (never captured):
   a. Ask the topic's questions (same as interview mode)
   b. Generate and save a new vault document
```

Refresh mode follows DP-1 — the user always sees existing content as a starting point, not a blank canvas. It follows DP-4 — after each refreshed topic, the engine reports what capability this restores: "Your projects list is current again. I'll reference it when you ask about priorities."

#### Mode D: Progressive Capture (automatic, during normal use)

Not a dedicated session. The Progressive Capture Hook operates during normal Harle conversations, detecting when the user reveals a preference or fact that the vault does not contain.

Detailed in Section "Progressive Capture Hook" below.

---

### 4. Progressive Capture Hook (learn from normal conversations)

**What it does:** Intercepts normal Orchestrator conversations to detect and save personal preferences, facts, and decisions. Operates transparently — the user's primary task proceeds uninterrupted while preferences are captured in the background.

**How it works:**

```
Normal conversation flow:

User: "Book me a hotel in Berlin"
                │
                ▼
    Agent processes the request
                │
                ▼
    Agent: "I'll search for hotels. Quick question —
            do you have a preference for hotel type?"
                │
                ▼
    User: "Boutique, mid-range budget"
                │
                ├──────────────────────────────┐
                ▼                              ▼
    Agent continues with            Progressive Capture Hook
    the hotel search                detects a preference:
                                    {
                                      category: "preference",
                                      content: "Prefers boutique
                                        hotels, mid-range budget",
                                      context_scope: "personal",
                                      confidence: 0.7
                                    }
                                           │
                                    ┌──────┴──────┐
                                    ▼             ▼
                              Memories        Optional:
                              Bridge          suggest vault
                              writes to       update to user
                              memories
                              table
```

**Detection rules (what triggers capture):**

| Signal | Example | Action |
|---|---|---|
| User answers a clarification question | "Which board?" → "Work Q1" | Save as preference with high confidence |
| User corrects the agent | "No, shorter paragraphs next time" | Save as correction with high confidence |
| User states an explicit preference | "I always want cost estimates in travel plans" | Save as preference with high confidence |
| User mentions a recurring pattern | "Every Monday I do task triage" | Save as preference with medium confidence |

**What is NOT captured progressively:**

- High-sensitivity topics (health, finances) — only captured in explicit interview sessions (DP-7).
- One-time context (e.g., "book this specific hotel for Friday") — task-specific, not a durable preference.
- Ambiguous statements — if confidence is below threshold, the preference is not saved.

**Periodic consolidation:**

Progressive captures accumulate in the `memories` table. Periodically (configurable, default: weekly), the module offers to consolidate:

```
Harle: "I've learned 8 new preferences this week.
        Want me to organize them into your vault documents?
        Here's a summary:
        - Travel: prefers boutique hotels, mid-range
        - Work: uses Linear for sprint tracking
        - Communication: wants cost breakdowns in reports
        ..."
```

Consolidation groups related memories by topic, generates or updates vault documents, and marks the memories as synchronized.

---

### 5. Health Checker (monitor vault quality)

**What it does:** Analyzes the vault for staleness, missing metadata, knowledge gaps, and structural issues. Produces a health report with actionable recommendations.

**When it runs:**
- On demand: `harle vault check`
- Scheduled: configurable interval (default: weekly)
- Proactive: during normal conversation when the agent notices stale context

**Health check pipeline:**

```
Step 1: STALENESS DETECTION
    Walk vault files, compare last_updated to current date.
    Flag files not updated in N days (configurable per topic,
    default: 90 days).
    
    Output:
    ⚠ 3 files not updated in 90+ days:
      - knowledge/work/projects/platform-migration.md (142 days)
      - knowledge/personal/goals/2025-goals.md (95 days)
      - workflows/quarterly-review.md (201 days)

Step 2: METADATA VALIDATION
    Check each vault file for required frontmatter fields:
    title, tags, context, last_updated, summary.
    
    Output:
    ⚠ 5 files missing frontmatter (title, tags, or context)

Step 3: STRUCTURAL ISSUES
    Check for overly large files (3000+ tokens),
    empty files, broken internal links.
    
    Output:
    ⚠ 2 files exceed recommended length (3000+ tokens)
    ✓ All files pass format validation

Step 4: COVERAGE ANALYSIS
    Compare Topic Registry topics against captured content.
    Identify topics that have never been captured or were
    skipped during onboarding.
    
    Output:
    ℹ Coverage: 60% (12 of 20 topics captured)
    ℹ Uncaptured topics:
      - Travel preferences (would enable trip planning)
      - Health notes (optional, private)
      - Areas of expertise (would improve technical responses)

Step 5: PROGRESSIVE CAPTURE BACKLOG
    Check memories table for un-consolidated progressive captures.
    
    Output:
    ℹ 8 preferences learned since last consolidation
      → Run "harle capture consolidate" to organize them
```

**Health report format:**

```
Vault Health Report
──────────────────
✓ 47 files indexed, 0 errors
⚠ 3 files not updated in 90+ days
⚠ 5 files missing frontmatter
⚠ 2 files exceed recommended length
ℹ Coverage: 60% (12/20 topics)
ℹ 8 un-consolidated progressive captures
✓ All files pass format validation

Recommended actions:
1. Refresh stale files: harle capture refresh
2. Fill missing topics: harle capture interview --tier 3
3. Consolidate recent captures: harle capture consolidate
```

**Proactive staleness prompts (during normal conversation):**

When the Orchestrator's Context Assembler loads a vault file that the Health Checker has flagged as stale, the agent can optionally append a note:

```
Harle: "I noticed your 'Current Projects' file hasn't been
        updated in 4 months. Want me to ask you a few questions
        and refresh it?"
```

This is controlled by a config flag (`capture.proactive_refresh: true`) and respects DP-5 (the user can dismiss it).

---

### 6. Profile Writer (write capture results to vault)

**What it does:** Takes generated Markdown content from the Capture Engine and writes it to the vault, handling directory placement, frontmatter generation, merge with existing content, and post-write indexing.

**Key design principle:** The Profile Writer never overwrites user edits blindly. When updating an existing vault document, it merges new content with the existing file, preserving sections the user has manually edited since the last capture.

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CaptureOutput:
    """A single vault document produced by the Capture Engine."""
    topic_id: str
    title: str
    content: str
    tags: list[str]
    context: str
    vault_path: str
    is_update: bool = False


class ProfileWriter:

    async def write(
        self,
        output: CaptureOutput,
        vault_path: Path,
    ) -> str:
        """Write a capture output to the vault.

        If the file exists and is_update is True, merge new
        content with existing content (see merge strategy below).
        If the file does not exist, create it with full frontmatter.

        Returns the vault-relative path of the written file.
        """
        ...

    async def merge_content(
        self,
        existing: str,
        new_content: str,
        topic_id: str,
    ) -> str:
        """Merge new capture content with an existing vault file.

        Strategy:
        1. Parse both files into sections (by heading level).
        2. For each section in the new content:
           - If a matching section exists in the old file
             AND the old section was not manually edited
             since last capture → replace with new content.
           - If the old section was manually edited → keep
             the user's version, append new facts as a
             sub-section marked "[Capture update]".
           - If the section is new → append it.
        3. Preserve all frontmatter fields from the existing
           file; update last_updated to current date.
        """
        ...
```

**Merge strategy illustrated:**

```
EXISTING FILE (user edited the "Tools" section manually):

---
title: "Work Profile"
tags: [work, profile]
context: work
last_updated: 2026-01-15
---

# Work Profile

## Role
Product Manager, Platform Team

## Tools I Use Daily       ← user edited this section
- Trello (board: "Work Q1")
- Notion (workspace: "Acme Corp")
- Slack
- **Linear** (added by user manually)

## Communication Style
Bullet points preferred


REFRESH captures updated role and new project info:

→ Merge result:

---
title: "Work Profile"
tags: [work, profile]
context: work
last_updated: 2026-03-01       ← updated
---

# Work Profile

## Role
Senior Product Manager, Platform Team    ← updated by capture

## Tools I Use Daily                     ← preserved (user-edited)
- Trello (board: "Work Q1")
- Notion (workspace: "Acme Corp")
- Slack
- **Linear** (added by user manually)

## Communication Style
Bullet points preferred, with cost estimates  ← updated by capture

## Current Projects                      ← new section added
- Platform migration (AWS → GCP)
- Harle: personal AI assistant
```

**Post-write actions:**

After writing, the Profile Writer:
1. Triggers a re-index of the written file (via the Indexer's sync mechanism) so it is immediately searchable.
2. Creates or updates corresponding `memories` entries via the Memories Bridge.
3. Updates the `capture_topic_progress` table to mark the topic as completed.

---

### 7. Memories Bridge (sync vault ↔ memories)

**What it does:** Keeps the `memories` database table and the vault files in sync. When the Capture Engine produces a vault document, the Memories Bridge extracts actionable facts and writes them as memory entries. When progressive capture adds memories, the bridge tracks which ones have been consolidated into vault files.

**Why both vault files and memories exist:**

| Vault files | Memories table |
|---|---|
| Human-readable, editable, version-controlled | Machine-queryable, confidence-scored, fast to filter |
| Full context and nuance ("I prefer boutique hotels because...") | Atomic facts ("Prefers boutique hotels, mid-range budget") |
| Source of truth for the user | Source of truth for the Context Assembler's quick lookups |
| Updated manually or via capture sessions | Updated automatically by progressive capture |

The bridge ensures they do not drift. When a vault file is updated (either by capture or by the user manually), the bridge re-extracts memories from it. When memories accumulate from progressive capture, the bridge marks them as un-consolidated until the next consolidation writes them to vault files.

```python
class MemoriesBridge:

    async def extract_memories(
        self, vault_content: str, topic_id: str, context: str
    ) -> list[dict]:
        """Extract atomic facts from a vault document.

        Uses the LLM to parse structured content into
        individual memory entries with categories and
        confidence scores.
        """
        ...

    async def consolidate_progressive(
        self, memories: list[dict], vault_path: Path
    ) -> str:
        """Merge un-consolidated progressive captures into
        a vault document.

        Groups related memories by topic, generates or updates
        the corresponding vault file, and marks memories as
        consolidated.
        """
        ...
```

---

## How It Works End-to-End

### Scenario 1: Initial Onboarding (Quick Profile → Interview)

```
1. User runs: harle init (or first interaction)

2. CLI detects empty vault → triggers Quick Profile
   a. Display 7-10 structured questions
   b. User answers in 5 minutes
   c. Profile Writer generates 2-3 vault files:
      - knowledge/work/profile.md
      - knowledge/personal/preferences.md
      - knowledge/personal/goals.md (if answered)
   d. Trigger re-index → files immediately searchable
   e. Memories Bridge extracts actionable facts → memories table

3. CLI suggests: "Want to do a deeper interview? (~10 min)
                  This helps me understand your work style better."

4. If yes → Capture Engine starts Interview mode (Tier 2)
   a. Session Manager creates a new session
   b. Topics from Tier 2 are selected (work hours, decisions, pain points)
   c. Conversational interview runs via conversation mode
   d. After each topic cluster: generate doc → user approves → save
   e. User can pause and resume later

5. Session completes → summary displayed:
   "Captured 8 topics across 5 vault files.
    Try asking me 'What should I focus on this week?'
    to see how I use what you told me."
```

### Scenario 2: Periodic Refresh

```
1. Health Checker runs (scheduled or manual: harle vault check)

2. Report identifies 3 stale files and 2 un-captured topics

3. User runs: harle capture refresh
   a. Session Manager creates a Refresh session
   b. For each stale topic:
      - Load existing vault content
      - Show to user: "Is this still accurate?"
      - User provides updates
      - Capture Engine generates updated document
      - Profile Writer merges with existing file
   c. For un-captured topics:
      - Run interview-style questions
      - Generate and save new vault documents

4. Session completes → summary:
   "Refreshed 3 files, added 2 new topics.
    Your vault coverage is now 80% (16/20 topics)."
```

### Scenario 3: Progressive Capture During Normal Use

```
1. User asks: "Help me plan a trip to Tokyo"

2. Agent processes the request, notices no travel preferences
   in vault → asks: "Do you have hotel preferences?"

3. User responds: "Boutique hotels, mid-range, central location"

4. Progressive Capture Hook detects a preference:
   a. Writes to memories table: category=preference,
      content="Boutique hotels, mid-range, central location",
      context=personal, confidence=0.7
   b. Optionally suggests: "I'll remember your hotel preferences
      for future trips."

5. Agent continues planning the trip using the new preference

6. Later (weekly consolidation):
   a. Harle: "I've learned 5 travel preferences this week.
              Want me to add them to your travel profile?"
   b. User approves → Memories Bridge consolidates into
      knowledge/personal/preferences/travel.md
```

---

## Configuration

Vault Capture Module configuration lives in the Orchestrator's `config.yaml` under the `capture` key.

```yaml
capture:
  # Quick Profile settings
  quick_profile:
    enabled: true
    trigger_on_empty_vault: true

  # Interview settings
  interview:
    model: "gpt-4o-mini"
    max_questions_per_cluster: 5
    max_session_duration_minutes: 30
    default_tiers: [1, 2]

  # Refresh settings
  refresh:
    staleness_threshold_days: 90
    proactive_refresh: true
    proactive_refresh_cooldown_days: 7

  # Progressive capture
  progressive:
    enabled: true
    min_confidence: 0.6
    sensitive_topics_excluded: true
    consolidation_interval_days: 7
    consolidation_auto_prompt: true

  # Health checker
  health:
    schedule: "weekly"
    staleness_threshold_days: 90
    max_file_tokens: 3000
    required_frontmatter: ["title", "tags", "context"]
    coverage_target: 0.8

  # Profile writer
  writer:
    merge_strategy: "preserve_user_edits"
    trigger_reindex: true
    generate_frontmatter: true
```

**Configuration sources (priority order):**

| Priority | Source | Example |
|---|---|---|
| **1 (highest)** | CLI flags | `--tier 3 --scope personal` |
| **2** | Environment variables | `HARLE_CAPTURE_MODEL=gpt-4o` |
| **3** | `config.yaml` values | `interview.model: gpt-4o-mini` |
| **4 (lowest)** | Module defaults (in code) | `staleness_threshold_days: 90` |

---

## CLI Integration

The Vault Capture Module extends the Harle CLI with two command groups: `capture` (for active knowledge capture) and additions to `vault` (for health monitoring).

```
harle capture <subcommand> [flags]

Subcommands:
  quick          Run the 5-minute quick profile questionnaire
  interview      Start (or resume) a conversational interview
  refresh        Re-interview on stale or incomplete topics
  consolidate    Organize progressive captures into vault documents
  status         Show current session status and topic coverage

Flags for 'interview':
  --tier <n>           Target tier (1-4, can specify multiple: --tier 1 --tier 2)
  --scope <scope>      Limit to a context: work, personal, goals, all (default: all)
  --resume             Resume a paused session
  --topic <id>         Interview on a specific topic only

Flags for 'refresh':
  --days <n>           Override staleness threshold (default: from config)
  --scope <scope>      Limit refresh to a context
  --topic <id>         Refresh a specific topic only

harle vault check [flags]

Flags:
  --scope <scope>      Limit health check to a context
  --fix-metadata       Auto-generate missing frontmatter fields
  --verbose            Show detailed per-file report
```

**Examples:**

```bash
# First-time setup (triggered automatically or manually)
harle capture quick

# Deep interview, work topics only
harle capture interview --scope work --tier 1 --tier 2

# Resume a paused interview
harle capture interview --resume

# Refresh stale content
harle capture refresh

# Refresh only travel preferences
harle capture refresh --topic travel_preferences

# Consolidate progressive captures into vault files
harle capture consolidate

# Check vault health
harle vault check

# Check vault health and auto-fix missing frontmatter
harle vault check --fix-metadata

# See current capture coverage
harle capture status
```

**CLI output example (capture status):**

```
Capture Status
──────────────
Session: none active (last completed 2026-02-20)

Topic Coverage:
  Tier 1 (Essential): ████████████████████ 100% (4/4 topics)
  Tier 2 (Useful):    ████████████░░░░░░░░  60% (3/5 topics)
  Tier 3 (Personal):  ████░░░░░░░░░░░░░░░░  25% (1/4 topics)
  Tier 4 (Goals):     ░░░░░░░░░░░░░░░░░░░░   0% (0/3 topics)

  Overall: 50% (8/16 topics captured)

Stale topics (not updated in 90+ days):
  - current_projects (last: 2025-12-01, 91 days ago)

Progressive captures pending consolidation: 5

Suggested next step:
  harle capture interview --tier 2
  (estimated time: 10 minutes, would cover 2 remaining work topics)
```

---

## Error Handling

| Error | What happens | User experience |
|---|---|---|
| **LLM unavailable during interview** | Session pauses automatically. Progress is saved. | "OpenAI API is down. Your session is saved — run `harle capture interview --resume` to continue." |
| **User closes CLI mid-session** | Session Manager detects disconnection, saves state as PAUSED. | On next run: "You have a paused capture session. Resume? [y/n]" |
| **Profile Writer cannot write to vault** | Error logged. Generated content stored in session progress (DB) for retry. | "Could not write to vault (permission denied). Your answers are saved. Fix permissions and run `harle capture interview --resume`." |
| **Merge conflict (manual + capture edit)** | Profile Writer preserves user edits, appends capture updates as new sections. Never overwrites. | "I noticed you edited the Tools section. I kept your version and added new information in a separate section." |
| **Topic already captured (re-interview without refresh)** | Session Manager warns and confirms. | "This topic was captured on 2026-02-15. Run with `--refresh` to update it, or `--force` to re-capture from scratch." |
| **Progressive capture confidence too low** | Preference is not saved. No user-visible action. | (Silent — the hook only saves above the confidence threshold.) |
| **Consolidation finds conflicting memories** | Memories with overlapping content are shown to the user for resolution. | "I have two travel preferences that seem contradictory: 'window seat' (Feb 10) and 'aisle seat' (Feb 25). Which is current?" |
| **Health Checker finds corrupt files** | Corrupt files are flagged in the report but not modified. | Report includes: "⚠ 1 file has invalid frontmatter: knowledge/work/profile.md — fix manually or run with --fix-metadata." |

---

## Technology Choices Summary

| Decision | Choice | Key reason |
|---|---|---|
| **Session persistence** | PostgreSQL (`capture_sessions` + `capture_topic_progress`) | Resumable across days/weeks; queryable by Health Checker |
| **Interview conversation** | Orchestrator's existing conversation mode | Reuse infrastructure; same LLM, same context assembly |
| **Topic definitions** | Python dataclasses loaded at startup | Declarative, type-safe, easy to extend |
| **Quick profile** | CLI-native structured input (no LLM) | Zero external dependency, works offline, fast |
| **Document generation** | LLM (configurable model, default GPT-4o-mini) | Natural language output, proper Markdown structure |
| **Merge strategy** | Section-level diffing via heading analysis | Preserves user edits while allowing updates |
| **Progressive capture** | Hook in Orchestrator's Agent Runner post-processing | Transparent to the agent; no changes to agent prompts |
| **Health scheduling** | Configurable interval in config.yaml | Simple; no external scheduler dependency |
| **Memories sync** | `MemoriesBridge` class bridging vault files ↔ DB | Single responsibility; keeps both stores consistent |
| **Frontmatter handling** | `python-frontmatter` library | Consistent with vault conventions and Data Layer |

---

## Incremental Implementation Plan

The Vault Capture Module is built in five phases. Each phase produces a working, testable result.

### Phase overview

```
Phase 1: Core infrastructure
    │     (topic registry, session manager, profile writer)
    │
    ├──→ Phase 2: Quick Profile (CLI, no LLM)
    │
    ├──→ Phase 3: Health Checker
    │
    └──→ Phase 4: Conversational Interview (LLM, conversation mode)
              │
              └──→ Phase 5: Progressive Capture + Consolidation
```

Phase 2 and Phase 3 can be developed in parallel after Phase 1. Phase 4 depends on the Orchestrator's conversation mode being functional. Phase 5 depends on the `memories` system.

---

### Phase 1: Core Infrastructure

**Goal:** Establish the topic registry, session manager, and profile writer. After this phase, the framework exists and can accept capture modes.

**What is built:**

| File | Contents |
|---|---|
| `src/harle/capture/__init__.py` | Package init, re-exports key classes |
| `src/harle/capture/topics.py` | `Topic`, `TopicQuestion`, `Tier`, `Sensitivity` dataclasses; topic tree definition |
| `src/harle/capture/registry.py` | `TopicRegistry` — loads topic definitions, queries by tier/scope/staleness |
| `src/harle/capture/run.py` | `CaptureRun`, `CaptureRunManager` — create, pause, resume, complete runs (avoids "session" vs chat sessions) |
| `src/harle/capture/writer.py` | `ProfileWriter` — write and merge vault files with frontmatter |

**Verification:** Unit tests with a mock vault directory. Create a run, mark topics as completed, write vault files, verify merge behavior.

**Dependencies:** PostgreSQL (for run tables). Database migration for `capture_runs` and `capture_run_topic_progress`.

**Estimated size:** ~450 lines of production code, ~300 lines of tests.

---

### Phase 2: Quick Profile

**Goal:** Deliver the minimum capture experience: a 5-minute CLI questionnaire that generates 2–3 vault files. No LLM required.

**What is built:**

| File | Contents |
|---|---|
| `src/harle/capture/quick_profile.py` | `QuickProfileRunner` — structured CLI questionnaire, response → vault document conversion |

**What changes:**

| Component | Change |
|---|---|
| **Go CLI** | Add `harle capture quick` subcommand. Sends structured input to the Orchestrator or runs locally. |
| **Bootstrap** (`bootstrap.py`) | On `harle init` with empty vault, trigger Quick Profile automatically. |

**Verification:**
- Answer all questions → verify 2–3 vault files created with proper frontmatter.
- Answer only 2 questions → verify at least 1 vault file created (DP-1).
- Skip all optional questions → verify mandatory questions still produce output.

**Dependencies:** Phase 1.

**Estimated size:** ~200 lines of production code, ~150 lines of tests.

---

### Phase 3: Health Checker

**Goal:** Build vault health monitoring: staleness detection, metadata validation, coverage analysis.

**What is built:**

| File | Contents |
|---|---|
| `src/harle/capture/health.py` | `HealthChecker` — staleness detection, metadata validation, coverage scoring, report generation |

**What changes:**

| Component | Change |
|---|---|
| **Go CLI** | Add `harle vault check` subcommand and `harle capture status` subcommand. |

**Verification:**
- Create a vault with stale files → verify they appear in the report.
- Create files with missing frontmatter → verify they are flagged.
- Verify coverage percentage matches captured vs. total topics.

**Dependencies:** Phase 1. Can run in parallel with Phase 2.

**Estimated size:** ~300 lines of production code, ~200 lines of tests.

---

### Phase 4: Conversational Interview

**Goal:** Build the core interview experience: an LLM-driven multi-turn conversation that generates vault documents from each topic cluster.

**What is built:**

| File | Contents |
|---|---|
| `src/harle/capture/engine.py` | `CaptureEngine` — orchestrates interview and refresh sessions, topic selection, follow-up generation, document creation |
| `src/harle/capture/prompts.py` | Interview prompt templates for the LLM (capture agent identity, instructions, format constraints) |

**What changes:**

| Component | Change |
|---|---|
| **Go CLI** | Add `harle capture interview` and `harle capture refresh` subcommands with flags. |
| **Orchestrator** | Add `/capture` endpoint group for session management and interview interaction. |

**Verification:**
- Start an interview session → verify questions follow the topic tree.
- Pause mid-session → verify state is saved → resume → verify continuation.
- Complete a tier → verify vault documents are generated with proper content.
- Run refresh on a stale topic → verify existing content is shown and updates are merged.

**Dependencies:** Phase 1. Requires Orchestrator conversation mode to be functional.

**Estimated size:** ~400 lines of production code, ~250 lines of tests.

---

### Phase 5: Progressive Capture + Consolidation

**Goal:** Build the passive learning system: detect preferences during normal conversations, save to memories, and consolidate into vault documents.

**What is built:**

| File | Contents |
|---|---|
| `src/harle/capture/progressive.py` | `ProgressiveCaptureHook` — preference detection, confidence scoring, memory writing |
| `src/harle/capture/bridge.py` | `MemoriesBridge` — vault ↔ memories sync, consolidation logic |
| `src/harle/capture/consolidation.py` | `ConsolidationRunner` — group related memories, generate/update vault documents |

**What changes:**

| Component | Change |
|---|---|
| **Agent Runner** | Hook into post-processing to call `ProgressiveCaptureHook` |
| **Go CLI** | Add `harle capture consolidate` subcommand |

**Verification:**
- Simulate a conversation where user reveals a preference → verify memory is created.
- Accumulate 5+ memories → run consolidation → verify vault document is generated.
- Verify high-sensitivity topics are excluded from progressive capture.
- Verify consolidation merges into existing vault files correctly.

**Dependencies:** Phase 1. Requires `db/memories.py` to be functional.

**Estimated size:** ~400 lines of production code, ~300 lines of tests.

---

### Phase dependency diagram

```
                    Phase 1
               Core Infrastructure
            (topics, sessions, writer)
                    │
            ┌───────┼───────┐
            │       │       │
            ▼       │       ▼
        Phase 2     │   Phase 3
        Quick       │   Health
        Profile     │   Checker
            │       │       │
            │       ▼       │
            │   Phase 4     │
            │   Interview   │
            │   + Refresh   │
            │       │       │
            └───────┼───────┘
                    │
                    ▼
                Phase 5
                Progressive
                Capture +
                Consolidation
```

### Effort estimates

| Phase | Estimated effort | Can parallelize with |
|---|---|---|
| **1. Core infrastructure** | 2–3 days | — |
| **2. Quick Profile** | 1–2 days | Phase 3 |
| **3. Health Checker** | 2–3 days | Phase 2 |
| **4. Conversational Interview** | 3–4 days | — |
| **5. Progressive Capture** | 3–4 days | — |
| **Total (sequential)** | ~2.5–3 weeks | |
| **Total (with parallelism)** | ~2–2.5 weeks | Phases 2+3 in parallel |

Estimates assume a single developer working part-time. The critical path is: Phase 1 → Phase 4 → Phase 5. Phases 2 and 3 can be built alongside Phase 4 to shorten the total timeline.

---

## Project Structure Summary

```
src/harle/capture/                     ← Vault Capture Module code
├── __init__.py
├── topics.py                          # Topic, TopicQuestion, Tier, Sensitivity
├── registry.py                        # TopicRegistry — topic definitions and queries
├── run.py                             # CaptureRun, CaptureRunManager
├── engine.py                          # CaptureEngine — interview/refresh orchestration
├── quick_profile.py                   # QuickProfileRunner — 5-min CLI questionnaire
├── writer.py                          # ProfileWriter — vault file writing and merging
├── health.py                          # HealthChecker — staleness, metadata, coverage
├── progressive.py                     # ProgressiveCaptureHook — passive learning
├── bridge.py                          # MemoriesBridge — vault ↔ memories sync
├── consolidation.py                   # ConsolidationRunner — group and write memories
└── prompts.py                         # Interview LLM prompt templates
```

**Key dependencies:**

| Package | Purpose |
|---|---|
| `sqlalchemy` + `asyncpg` | Session persistence in PostgreSQL |
| `python-frontmatter` | Generate and parse YAML frontmatter for vault files |
| `openai` | LLM calls for interview conversation and document generation |
| `tiktoken` | Token counting for generated documents |

---

## Relationship to Other Components

| Component | Relationship |
|---|---|
| **Import Module Layer** | Independent. Import handles external data (Notion, Miro); Capture handles knowledge from the user's head. Both write to the vault via their own writers, both trigger re-indexing. |
| **Tool Module Layer** | The Capture Engine reuses the Orchestrator's conversation mode, which uses the Agent Runner and tools. Progressive capture hooks into the Agent Runner's post-processing. |
| **Data Layer (Indexer)** | Profile Writer triggers re-index after writing. Health Checker queries `file_index` for metadata validation. Capture session tables are added to the Indexer's PostgreSQL database. |
| **Orchestrator** | The Capture Engine runs inside the Orchestrator process. Interview sessions use conversation mode. The `/capture` endpoint group is added to the HTTP API. |
| **CLI** | The `capture` and `vault check` commands are added to the Go CLI. Quick Profile can run standalone (no Orchestrator needed). |
| **Vault (User Dataset)** | Capture writes to `knowledge/work/` and `knowledge/personal/`. All files follow vault conventions (Markdown, YAML frontmatter, directory structure per `data.md`). |
| **Memories System** | MemoriesBridge writes and reads from the `memories` table. Progressive capture creates memories; consolidation reads them and writes vault files. |
