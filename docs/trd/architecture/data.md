---
title: "Harle Data Layer — Architecture & Functionality"
tags: [data-layer, architecture, dataset, indexer, search, postgresql, whoosh]
context: global
last_updated: 2026-03-25
summary: "Describes the three data components — User Dataset, Indexer, and Search Algorithm — their internal architecture, interactions, and technology choices."
---

# Harle Data Layer — Architecture & Functionality

> The Data Layer is everything that stores, indexes, and retrieves information in Harle. It is the reason Harle can be personalized — without it, the system would be a generic chatbot with no memory, no context, and no knowledge of your rules.

This document describes the three data components — the User Dataset (files), the Indexer (database), and the Search Algorithm — their internal architecture, how they interact, and the technology choices behind each part. It is written for someone who may not have deep backend experience.

For the overall system architecture, see [overview.md](./overview.md).  
For the Orchestrator (which consumes data from this layer), see [orchestrator.md](./orchestrator.md).

---

## Fundamental Principle: Data Is External to the Code Repository

**All data — the User Dataset, the PostgreSQL database state, and runtime configuration — lives outside the Harle application repository.** This repository contains the application code, documentation, and configuration templates. It never contains user-specific data.

This separation is foundational, not optional:

- **The User Dataset (vault)** is a separate directory or Git repository on disk (e.g. `~/harle-vault`). The Orchestrator reads its location from `config.yaml` (`dataset.path`) or the `HARLE_DATASET_PATH` environment variable.
- **The PostgreSQL database** runs as a separate service (Docker container, managed instance, or system install). Its data directory is a Docker volume or a system path — never inside this repository.
- **Runtime configuration** (`config.yaml` with actual paths, secrets, and per-deployment settings) lives outside the repo (e.g. `~/.config/harle/config.yaml`). The repository provides only a `config.example.yaml` template.

**Why:**
1. **Multi-user support.** Different users share the same Harle codebase but each has their own vault, database, and config. A user clones this repo, creates their own vault, and runs Harle — no fork needed for customization.
2. **Clean versioning.** Code changes (features, fixes) and data changes (new notes, run logs) are independent version histories. They never create merge conflicts with each other.
3. **Safety.** Personal data, API keys, and private knowledge never risk being committed to the application repository — even by mistake.
4. **Upgradeability.** Pulling a Harle update (`git pull`) never touches your data. Moving your vault to a new machine never touches the code.

For the full explanation of this principle, see the "Key Architectural Principle" section in [overview.md](./overview.md).

---

## Where the Data Layer Sits

```
                    ORCHESTRATOR
                         │
          ┌──────────────┼──────────────┐
          │              │              │
          ▼              ▼              ▼
  ┌──────────────┐ ┌──────────┐ ┌─────────────┐
  │   Search     │ │ Indexer   │ │   User      │
  │   Algorithm  │ │ (Postgres)│ │   Dataset   │
  │   (Whoosh)   │ │          │ │   (files)   │
  └──────┬───────┘ └────┬─────┘ └──────┬──────┘
         │              │              │
         │         reads/writes        │
         │              │              │
         └──────────────┼──────────────┘
                        │
              all three work together
              to answer one question:
          "what does the agent need to know?"
```

The Data Layer is not a single service. It is three components that work together:

1. **User Dataset** — the source of truth. Your Markdown files, notes, prompts, policies, and knowledge. This is what you create and edit.
2. **Indexer** — the database. Stores structured metadata about the dataset, agent run logs, and (later) vector embeddings. This is what makes data queryable.
3. **Search Algorithm** — the bridge. Takes a request from the Orchestrator, queries both the dataset and the Indexer, and returns the most relevant results. This is what makes data findable.

Their combined purpose is to answer one question for every request: **"Given what the user asked, which pieces of their data should the agent see?"**

---

## Why the Data Layer Is Split in Three

A natural question: why not just use a database? Or just search the files directly? The three-way split exists because each component solves a different problem:

| Component | What it is good at | What it cannot do alone |
|---|---|---|
| **User Dataset (files)** | Human-readable, editable, version-controlled. You can browse, edit, and organize it with any tool. | Slow to search at scale. No structured queries. No metadata tracking. |
| **Indexer (database)** | Fast structured queries. Tracks metadata, run logs, relationships. Stores vector embeddings. | Not human-friendly. You would not edit a Postgres row to update your writing style rules. |
| **Search Algorithm** | Finds the right content fast, across both files and database. Handles the context window problem. | Stores nothing — it is a read-only query layer. |

**The key design principle:** Your data lives in files (human-first). The database mirrors and enriches it (machine-first). The search connects them to every request.

```
You (human)                          Harle (machine)
    │                                      │
    │ edit Markdown files ───────> User Dataset (files)
    │                                      │
    │                               Indexer mirrors it,
    │                               adds metadata,
    │                               tracks runs & history
    │                                      │
    │                               Search Algorithm
    │                               finds what's relevant
    │                                      │
    │                               Agent sees only the
    │                               5–10 most relevant pages
```

---

## 1. User Dataset (your files)

### What it is

The User Dataset is a directory of plain files — primarily Markdown — organized in folders. It is the **source of truth** for everything Harle knows about you: your rules, preferences, writing style, project notes, agent prompts, workflow templates, and knowledge base.

Think of it as your personal Wikipedia, but private and editable.

### Technology: Markdown files in a separate Git repository (not the Harle code repo)

The vault is its own Git repository, completely independent from the Harle application repository. This is a deliberate design decision — see "Fundamental Principle" above.

**Why Markdown:**
- **Human-readable.** Open any file in any text editor and it makes sense. No special viewer needed.
- **Lightweight.** A 2-page note is ~4 KB. You can have thousands of files without worrying about storage.
- **Structured enough.** Markdown supports headers, lists, tables, links, and code blocks — enough structure for search and parsing, but not so rigid that it becomes annoying to write.
- **Universal.** Markdown is supported by Obsidian, Notion (export), GitHub, VS Code, Cursor, and hundreds of other tools.

**Why its own Git repository (separate from the Harle code):**
- **Different lifecycle.** Application code changes with features and bug fixes. Your vault changes daily as you add notes, agents write logs, and preferences evolve. These are independent versioning streams.
- **Multi-user support.** Two users running the same Harle codebase have completely different vaults. The vault is personal; the code is shared.
- **Full history.** Every change to every file is tracked — who changed it, when, and what exactly changed. If an agent modifies a file badly, you can revert.
- **Two-computer sync.** Push from one machine, pull on the other. The dataset stays consistent.
- **Conflict detection.** If you edit a file on your laptop while an agent edits it on the server, Git shows the conflict instead of silently overwriting.
- **Different access controls.** The code repo may be public. The vault is private and contains personal data.
- **Branching (future).** Agents could work on a branch and you merge their changes after review — like a code review, but for your knowledge base.

### Dataset structure

The dataset has a specific directory layout. Each directory has a purpose, and agents know where to look for different types of content.

```
~/harle-vault/                         ← Separate Git repo, NOT inside the Harle code repo
│
├── prompts/                    # Agent role definitions
│   ├── researcher.md           #   How the Researcher agent should behave
│   ├── secretary.md            #   How the Secretary agent should behave
│   └── specialist.md           #   How the Specialist agent should behave
│
├── policies/                   # Rules and constraints
│   ├── privacy.md              #   What data can be shared, what stays private
│   ├── tools-allowlist.md      #   Which tools each agent is allowed to use
│   └── approval-rules.md       #   When write actions need user approval
│
├── workflows/                  # Reusable task templates
│   ├── weekly-status.md        #   Steps for writing a weekly status report
│   ├── product-hypothesis.md   #   Steps for evaluating a product idea
│   ├── task-triage.md          #   Steps for triaging stalled Trello tasks
│   └── travel-planning.md      #   Steps for planning a trip
│
├── knowledge/                  # Your personal knowledge base
│   ├── work/                   #   Work-related notes (separate context)
│   │   ├── projects/           #     Per-project information
│   │   ├── architecture/       #     Technical architecture notes
│   │   └── decisions/          #     Past decisions and rationale
│   └── personal/               #   Personal notes (separate context)
│       ├── preferences/        #     Writing style, formatting preferences
│       ├── travel/             #     Travel plans, preferences
│       └── health/             #     Health notes (private)
│
├── examples/                   # Example inputs/outputs for agents
│   ├── good-goals.md           #   Examples of well-defined task requests
│   └── report-samples.md       #   Examples of reports in your preferred format
│
└── logs/                       # Agent run artifacts (auto-generated)
    └── 2026/
        └── 02/                 #   Date-based: YYYY/MM for log-friendly search
            ├── run_2026-02-12_001.md   # Result + optional context + execution trace (one file)
            └── run_2026-02-12_002.md
```

### How each directory is used

| Directory | Who reads it | Who writes it | When it is used |
|---|---|---|---|
| `prompts/` | Orchestrator (every request) | You (manually) | Loaded as the agent's identity and instructions on every run |
| `policies/` | Context Assembler (every request) | You (manually) | Included in context to enforce rules and constraints |
| `workflows/` | Router + Context Assembler | You (manually); Specialist agent (suggests improvements) | Matched against requests; used as step-by-step templates |
| `knowledge/` | Search Algorithm (when relevant) | You (manually); agents (with approval) | Searched on every request; relevant files included in context |
| `examples/` | Context Assembler (when helpful) | You (manually) | Included as few-shot examples to guide agent output format |
| `logs/` | Search Algorithm; Specialist agent | Run Logger (automatically) | Referenced for past decisions; analyzed for system improvement |

### Logs directory: structure, format, and search

The `logs/` directory holds **agent run artifacts**: result summaries and, optionally, the assembled prompt (Context Assembler output) for each run. Logs are written by the Run Logger for successful and non-success runs alike; they must be **searchable at scale** and **easy to open** in an editor or viewer.

**Directory structure (date-based, log-friendly):**

```
logs/
├── 2026/
│   ├── 01/
│   │   ├── run_2026-01-15_001.md
│   │   └── run_2026-01-15_002.md
│   └── 02/
│       ├── run_2026-02-12_001.md
│       └── run_2026-02-12_002.md
└── ...
```

- **Path pattern:** `logs/YYYY/MM/<safe_stem>.md` where `<safe_stem>` is derived from `run_id` (special characters sanitized for the filesystem; the full `run_id` remains in YAML frontmatter). Each file contains **# Result**, optional **# Assembled context** (when context logging is enabled), and optional **# Execution trace** (when vault tracing is enabled and OTel export ran). The `run_id` is unique (e.g. `run_abc12def3456`) and date folders allow **time-bounded listing** and keep each directory from growing unbounded.
- **Opening a log:** Given a `run_id` or `result_path` from the Indexer, the user opens the single merged file (e.g. `logs/2026/02/run_2026-02-12_001.md`). The `runs.context_path` column is deprecated for new runs (always `NULL`); context lives in the same file when stored.

**File format (human-readable, machine-parseable):**

Each log file is Markdown with an optional **YAML frontmatter** block so both humans and tools can use it:

```markdown
---
run_id: run_2026-02-12_001
timestamp: "2026-02-12T14:32:00Z"
agent: secretary
status: completed
context_scope: work
conversation_id: conv_7f3a
total_spans: 12
duration_ms: 2100
---

# Result

Summary of what the agent returned...
```

- **Merged run log** (`<safe_stem>.md`): frontmatter + **# Result** + optional **# Assembled context** + optional **# Execution trace**. Full output for `completed` runs, or a short failure/timeout/abort summary for non-success runs. The Indexer stores metadata in `runs` and `result_path` points here. Assembled prompt/context can be disabled via config. For new runs, `context_path` on `runs` is always `NULL` when context is embedded; legacy rows may still reference older split files.

**Expected terminal statuses:**
- `completed`
- `failed`
- `timeout`
- `aborted` (best-effort, usually for detected client disconnects/cancellations)

**Minimum guaranteed data for early-failure logs:**
- `run_id`
- timestamp
- `user_request`
- `context_scope`
- terminal `status`
- `conversation_id` if it was already known

When more execution state is available, the same run can also include `files_used`, `tools_called`, elapsed time, result summary, and optional assembled context.

This format stays **plain Markdown** so logs are easy to open and read; frontmatter supports scripting and classic log tooling (e.g. filter by `agent`, `status`, or `timestamp` in the first few lines).

**Searching logs (classic techniques at scale):**

With a large number of runs, **search should not rely on scanning every file**. The design splits roles:

| Need | Where it lives | How to search |
|------|----------------|---------------|
| **By time range, agent, status, cost** | Indexer `runs` table | SQL (e.g. `WHERE timestamp BETWEEN ... AND agent = 'secretary'`). Fast, indexed. |
| **By user request or result summary text** | Indexer `runs` table | PostgreSQL full-text search (e.g. `tsvector` on `user_request`, `result_summary`). |
| **By full body of results/context** | Vault `logs/` files | Optional: index log files in Whoosh (same as rest of dataset) or store excerpts in DB. Default: search via `runs` metadata + open by `result_path`/`context_path`. |
| **Open a specific run** | Vault `logs/` | Use `result_path` or `context_path` from `runs`; or construct path from `run_id` and date. |

So **classic log search** (time range, level/status, agent, full-text on message/summary) is done against the **Indexer**; the vault holds the **durable, human-readable artifact** and a stable path for opening. Optionally, log file bodies can be included in the dataset Whoosh index so "find runs where the result mentioned X" works without storing full bodies in PostgreSQL. Retention (e.g. delete or archive logs older than N months) can be implemented by pruning both `runs` rows and the corresponding files under `logs/`. The `runs` table is intentionally **not limited to completed runs**; failed, timed-out, and best-effort aborted runs also appear there so listing/detail views can surface operational issues alongside successful runs.

### File format conventions

Every Markdown file in the dataset follows simple conventions that help the Search Algorithm index it and the Orchestrator use it:

**Frontmatter (YAML header):**

```markdown
---
title: "Privacy Policy for Work Context"
tags: [privacy, work, policy]
context: work
last_updated: 2026-02-10
---

# Privacy Policy for Work Context

Do not include employee names in reports sent outside the team.
...
```

**Why frontmatter:**
- **Tags** let the Search Algorithm find files by category, not just by content. Searching for `tag:privacy` is faster and more precise than scanning every file for the word "privacy."
- **Context** (`work` or `personal`) lets the system respect boundaries. When you ask a question in "work" context, personal files are excluded from search results.
- **Title** and **last_updated** help with ranking — newer, specifically titled files rank higher than old, vaguely titled ones.

**Frontmatter is optional.** Files without it still work — they are just indexed by content alone. You can add frontmatter gradually as the dataset grows.

### How agents modify the dataset

Agents can write to the dataset, but with strict controls:

```
Agent wants to write a file
         │
         ▼
    Is context "work"?
    ┌────┴────┐
   yes       no
    │         │
    ▼         ▼
  Requires  Check policy:
  approval  personal writes
  always    may auto-approve
    │       for low-risk
    │       directories
    ▼       (e.g. logs/)
  User approves → file written
  User denies  → action skipped, agent continues
```

**What agents typically write:**
- Run result summaries (to `logs/`).
- New knowledge files (e.g. a research report saved to `knowledge/work/`).
- Updated workflow templates (Specialist agent improving existing templates).

**What agents never write without explicit approval:**
- Changes to `prompts/` (would change agent behavior).
- Changes to `policies/` (would change system rules).
- Deletion of any file.

### Syncing between machines

The dataset must be accessible from both the server (where the Orchestrator runs) and your computers (where you edit files).

**Primary method: Git (the vault has its own Git remote, separate from the Harle code repo)**

```
Your laptop           Vault Git remote         Server
    │                 (private GitHub/Gitea)        │
    │  git push ──────────>│                        │
    │                      │<──── git pull ─────────│
    │                      │                        │
    │  You edit files      │     Orchestrator reads │
    │  in ~/harle-vault/   │     vault from the     │
    │  and push            │     configured path    │
    │                      │     (dataset.path)     │

Note: The Harle code repo and the vault repo are completely
independent. They have different remotes, different commit
histories, and different access controls.
```

The server pulls the latest dataset on startup and at regular intervals (e.g. every 5 minutes), or on demand when a request comes in and the dataset is stale.

**Alternative: Syncthing** — for real-time, automatic sync without manual pushes. Better for rapid iteration when you are actively editing the dataset while using Harle.

---

## 2. Indexer (PostgreSQL database)

### What it is

The Indexer is a PostgreSQL database that stores structured, queryable data about your dataset and the system's history. It does not replace the files — it **mirrors and enriches** them with metadata, relationships, and search-optimized representations.

Think of it this way: the User Dataset is a library of books. The Indexer is the library's catalog system — it tells you which books exist, what they are about, when they were last checked out, and where to find them.

### Technology: [PostgreSQL](https://www.postgresql.org/) 16+ with [pgvector](https://github.com/pgvector/pgvector)

**The database runs as a separate service, external to the Harle code repository.** In development, it runs as a Docker container with a named volume for persistence. In production, it can be a managed PostgreSQL instance or a system-installed Postgres. The connection URL is configured via `config.yaml` (`indexer.database_url`) or the `DATABASE_URL` environment variable. Database state (tables, data, indices) is per-user runtime data — it is never committed to the code repository.

### Database schema

The Indexer contains six core tables. Each serves a different purpose.

#### Table 1: `file_index` — what is in the dataset

Mirrors the file system. Every file in the User Dataset has a row here with metadata for fast querying.

```sql
CREATE TABLE file_index (
    id              SERIAL PRIMARY KEY,
    file_path       TEXT NOT NULL UNIQUE,    -- "knowledge/work/projects/harle.md"
    title           TEXT,                     -- From frontmatter or first heading
    tags            TEXT[],                   -- From frontmatter: ["privacy", "work"]
    context         TEXT,                     -- "work" or "personal"
    content_hash    TEXT NOT NULL,            -- SHA-256 of file content (detect changes)
    char_count      INTEGER,                 -- File size in characters
    token_count     INTEGER,                 -- Estimated token count (for budget planning)
    summary         TEXT,                     -- Auto-generated 1-2 sentence summary
    last_modified   TIMESTAMP NOT NULL,       -- File system modification time
    last_indexed    TIMESTAMP NOT NULL,       -- When this row was last updated
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
```

**Why this table exists:**
- **Fast filtering.** "Give me all files tagged 'privacy' in the 'work' context" is a millisecond query. Scanning the file system would take seconds.
- **Change detection.** The `content_hash` lets the system know if a file changed since last indexing — only changed files need re-processing.
- **Token budgeting.** The Context Assembler uses `token_count` to know how much of the token budget a file will consume before loading it.
- **Summaries.** Auto-generated summaries let the Search Algorithm and Context Assembler decide relevance without reading the full file.

#### Table 2: `runs` — execution history

Every Orchestrator execution produces one row. This is the structured version of the Run Logger's output (see [orchestrator.md](./orchestrator.md)).

```sql
CREATE TABLE runs (
    id              SERIAL PRIMARY KEY,
    run_id          TEXT NOT NULL UNIQUE,     -- "run_2026-02-12_001"
    timestamp       TIMESTAMP NOT NULL,
    user_request    TEXT NOT NULL,            -- What the user asked
    context_scope   TEXT NOT NULL,            -- "work" or "personal"
    agent           TEXT NOT NULL,            -- "secretary", "researcher", "specialist"
    routing_method  TEXT,                     -- "keyword_match", "llm_fallback", etc.
    status          TEXT NOT NULL,            -- "completed", "failed", "timeout", "aborted"
    
    -- Context tracking
    files_used      TEXT[],                   -- Which dataset files were in context
    tools_called    TEXT[],                   -- Which tools were invoked
    
    -- Cost tracking
    model_used      TEXT,                     -- "gpt-4o-mini", "gpt-4o"
    tokens_input    INTEGER,
    tokens_output   INTEGER,
    estimated_cost  NUMERIC(10,6),           -- In USD
    duration_ms     INTEGER,
    
    -- Result
    result_summary  TEXT,                     -- Short summary of the output
    result_path     TEXT,                     -- Path to full result in vault logs/
    
    -- Conversation
    conversation_id TEXT,                     -- NULL for one-shot, ID for chat
    
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
```

**Why this table exists:**
- **Debugging.** "Why did the agent give a bad answer on Tuesday?" — query the run, see what files and tools were used.
- **Cost tracking.** "How much did I spend this week?" — `SELECT SUM(estimated_cost) FROM runs WHERE timestamp > ...`
- **Quality improvement.** "Which requests take the most iterations?" — find patterns to optimize with better prompts or workflow templates.
- **The Specialist agent** uses this table to analyze system performance.

The `runs` table stores **all terminal outcomes**, not just successful ones. Similarity search and prior-run retrieval may deliberately filter to `completed` runs for relevance, but operational listing/detail views should expect to see `failed`, `timeout`, and `aborted` rows as well.

**Where to store the assembled prompt (Context Assembler output):**  
The full prompt built by the Context Assembler (system prompt + policies + search results + conversation slice) is not stored in the database — the `runs` table only keeps metadata (`files_used`, token counts, etc.). The **recommended place** to persist it is the **User Dataset** under `logs/`, in the **same merged file** as the run result and (when enabled) the execution trace: see [Logs directory](#logs-directory-structure-format-and-search). The **# Assembled context** section is included when `logging.store_assembled_context` (or equivalent) is on; otherwise that section is omitted.

- **Search:** Log search (by time, agent, status, or full-text on request/summary) is done via the **Indexer** (`runs` table and optional full-text indexes), not by scanning vault files — see the logs subsection for the split between DB-backed search and vault-backed storage.
- **Opening:** User opens the merged file by `result_path`. The `context_path` column remains for legacy rows; new runs set it to `NULL` when context is embedded. If the application must fetch the assembled prompt by `run_id` without reading the vault (e.g. for retention or API), the content can alternatively be stored in a `run_contexts` table in PostgreSQL for programmatic access.
- **Disconnect limitation:** Client-disconnect detection is best-effort in the current HTTP/threadpool runtime shape. Harle reliably records pre-start disconnects, but mid-flight disconnects may only be reflected indirectly through timeout/failure handling if the worker thread continues running after the client connection is gone.

#### Table 3: `artifacts` — agent outputs

Large outputs (research reports, status summaries, generated documents) stored separately from run logs.

```sql
CREATE TABLE artifacts (
    id              SERIAL PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    artifact_type   TEXT NOT NULL,            -- "report", "summary", "plan", "analysis"
    title           TEXT,
    content         TEXT NOT NULL,            -- Full content
    file_path       TEXT,                     -- Path in vault if saved to file
    context_scope   TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
```

**Why this table exists:**
- **Retrieval.** "Show me the research report you wrote last week" — query by type and date.
- **Context for future runs.** The Context Assembler can reference past artifacts when handling similar requests.
- **Separate from run logs.** Run logs contain metadata (tokens, cost, tools). Artifacts contain the actual output. Keeping them separate means you can query each efficiently.

#### Table 4: `memories` — learned preferences and decisions

Stores things Harle learns about you over time — your preferences, recurring decisions, and explicit corrections.

```sql
CREATE TABLE memories (
    id              SERIAL PRIMARY KEY,
    category        TEXT NOT NULL,            -- "preference", "decision", "correction"
    content         TEXT NOT NULL,            -- "User prefers bullet-point format"
    context_scope   TEXT NOT NULL,            -- "work", "personal", or "global"
    source_run_id   TEXT,                     -- Which run created this memory
    confidence      NUMERIC(3,2),            -- 0.00 to 1.00
    active          BOOLEAN DEFAULT TRUE,     -- Can be disabled without deletion
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
```

**Why this table exists:**

Without memory, Harle asks the same clarifying questions every time. With memory:

| Without memories | With memories |
|---|---|
| "What format do you want the report in?" | (knows you prefer bullet points — skips the question) |
| "Which Trello board?" | (knows your work board is "Work Q1" — uses it automatically) |
| "Should I include budget details?" | (knows you always want budget info for travel tasks) |

Memories are created from:
- **Explicit corrections.** You say "next time, use shorter paragraphs" — stored as a preference.
- **Clarification answers.** Your answers to clarification questions become memories for next time.
- **Repeated patterns.** If you always approve a certain type of action, the Specialist agent can suggest creating a memory for it.

Memories have a `confidence` score. New memories start at a low confidence and increase as they are confirmed by repeated use. The Context Assembler includes high-confidence memories automatically and may ask about low-confidence ones.

#### Table 5: `conversations` — multi-turn chat history

Stores conversation state for the chat mode.

```sql
CREATE TABLE conversations (
    id                SERIAL PRIMARY KEY,
    conversation_id   TEXT NOT NULL UNIQUE,
    context_scope     TEXT NOT NULL,
    agent_role        TEXT NOT NULL,
    summary           TEXT,                  -- Running summary of older messages
    active            BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE messages (
    id                SERIAL PRIMARY KEY,
    conversation_id   TEXT NOT NULL REFERENCES conversations(conversation_id),
    role              TEXT NOT NULL,          -- "user" or "assistant"
    content           TEXT NOT NULL,
    run_id            TEXT,                   -- Link to the run that produced this message
    created_at        TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### Table 6: `embeddings` — vector representations (future)

For semantic search via pgvector. Not in the first version, but the table is designed now so the schema does not need restructuring later.

```sql
CREATE TABLE embeddings (
    id              SERIAL PRIMARY KEY,
    source_type     TEXT NOT NULL,            -- "file", "artifact", "memory"
    source_id       INTEGER NOT NULL,         -- ID in the source table
    chunk_index     INTEGER NOT NULL,         -- Position within the source (large files are split)
    chunk_text      TEXT NOT NULL,            -- The actual text that was embedded
    embedding       vector(1536),            -- pgvector column (OpenAI embedding dimensions)
    model           TEXT NOT NULL,            -- "text-embedding-3-small"
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
```

**What are embeddings?**  
An embedding is a list of numbers (a "vector") that represents the meaning of a piece of text. Two pieces of text with similar meaning will have similar vectors. This enables **semantic search** — finding documents by meaning, not just by matching keywords.

Example: searching for "data protection approaches" would also find a document titled "privacy solutions for institutional clients" even though no keywords overlap — because their meanings are similar.

**Why later:**  
Full-text search (Whoosh) is sufficient for the first version and has no dependencies. Semantic search adds significant value for vague or conceptual queries, but requires an embedding API (additional cost and complexity). It is the natural next step once the core loop works.

### How the Indexer stays in sync with the dataset

The User Dataset (files) is the source of truth. The Indexer must stay in sync with it. Here is how:

```
┌─────────────────────────────────────────────────────┐
│                   SYNC PROCESS                       │
│                                                      │
│  Trigger: server startup, periodic (every 5 min),    │
│           or on-demand before a request               │
│                                                      │
│  1. Walk the dataset directory                       │
│     → List all .md files                             │
│                                                      │
│  2. Compare with file_index table                    │
│     → For each file, check content_hash              │
│     → If hash matches → skip (no changes)            │
│     → If hash differs → re-index                     │
│     → If file missing from DB → add it               │
│     → If DB row has no matching file → mark deleted   │
│                                                      │
│  3. Re-index changed files                           │
│     → Parse frontmatter (title, tags, context)       │
│     → Count characters and estimate tokens           │
│     → Generate/update summary (LLM call, cached)     │
│     → Update Whoosh full-text index                  │
│     → (Future) Generate/update embeddings            │
│                                                      │
│  4. Report                                           │
│     → Log: "Indexed 3 new files, updated 1, 497 total"│
└─────────────────────────────────────────────────────┘
```

**Why hash-based change detection:**
- **Fast.** Computing SHA-256 of a file is microseconds. Comparing 500 hashes takes less than a millisecond.
- **Accurate.** Only truly changed files are re-processed. No wasted work.
- **No file system watcher needed.** File watchers (like inotify) are platform-dependent and unreliable with synced files (Git, Syncthing). Hash comparison is simple and works everywhere.

**Cost of re-indexing:**
- **File parsing and Whoosh update:** free, milliseconds per file.
- **Summary generation (LLM call):** ~$0.001 per file. Only runs for new or changed files. For a typical session (1–5 file changes), the cost is negligible.
- **(Future) Embedding generation:** ~$0.0001 per file chunk via OpenAI's embedding API.

---

## 3. Search Algorithm

> **Detailed design:** This section provides a high-level summary. For the full architecture — the complete pipeline, query expansion, Whoosh internals, chunking strategy, ranking formulas, semantic search roadmap, migration plan, and configuration — see **[search.md](./search.md)**.

### What it is

The Search Algorithm is the query engine that sits between the Orchestrator and the data stores. When the Orchestrator needs relevant context for a request, it asks the Search Algorithm: "What in the dataset is relevant to this question?"

The Search Algorithm is **stateless** — it does not store data. It queries both the Whoosh full-text index and the PostgreSQL Indexer to find and rank results.

### The core problem it solves

As explained in [overview.md](./overview.md), language models have a limited context window. Your dataset can be far larger than this window. The Search Algorithm's job is to **reduce thousands of pages to the 5–10 most relevant ones**.

```
Full dataset                    Search Algorithm              Agent sees
(1,000+ pages)                  narrows it down               (5–10 pages)

┌──────────────┐                                         ┌──────────────┐
│ prompts/     │                                         │ secretary.md │
│ policies/    │     query: "stalled Trello tasks"       │ task-triage  │
│ workflows/   │ ──────────────────────────────────────> │   .md        │
│ knowledge/   │           relevance ranking             │ approval-    │
│   500+ files │                                         │   rules.md   │
│ logs/        │                                         │ 2 prior runs │
│ examples/    │                                         └──────────────┘
└──────────────┘
```

This is not a web search engine — it solves **context selection** for an LLM. The requirements differ: it must return file content (not links), pick the right results automatically (the user does not browse), and respect a hard token budget.

### Technology: [Whoosh](https://whoosh.readthedocs.io/) full-text search + PostgreSQL metadata queries

### Evolution plan (three phases)

The Search Algorithm evolves in three phases. Each phase works on its own; later phases extend, not replace, earlier ones.

| Phase | Engine | Status | When to use |
|---|---|---|---|
| **Phase 1** | Simple keyword search | **Implemented** | Datasets < 100 files. Scans all files, scores by case-insensitive term matching. |
| **Phase 2** | Whoosh BM25 + metadata pre-filter | Target (next) | Datasets 100–1,000 files. Inverted index, field boosts, query expansion, sub-50ms queries. |
| **Phase 3** | Hybrid: Whoosh + pgvector semantic | Future | Datasets > 500 files or when vocabulary mismatch becomes a problem. |

The current Phase 1 implementation (`search/engine.py`) iterates all indexed files, loads content from disk, and scores by weighted term frequency (title 3x, tag 2x, content 0.5x capped at 3.0 per term). It has zero dependencies beyond PostgreSQL and works out of the box for small datasets, but degrades linearly with file count (O(n) disk I/O per query).

**The migration to Phase 2 does not change the public interface.** `SearchEngine.search(query) → list[SearchResult]` remains stable — only the internal implementation evolves. See [search.md — Migration Path](./search.md#migration-path) for details.

### How a search query works (Phase 2 pipeline)

```
Input: user request + agent role + context scope
         │
Step 1: QUERY EXPANSION — extract terms, add role-specific terms, match tag vocabulary
Step 2: METADATA PRE-FILTER — PostgreSQL narrows candidates by context, tags, priority
Step 3: FULL-TEXT SEARCH — Whoosh BM25 scores candidates with field boosts (title 2x, tags 1.5x)
Step 4: METADATA ENRICHMENT — load token_count, summary, recency for top results
Step 5: MEMORY & HISTORY — search memories and past runs for relevant context
Step 6: RANKING & FUSION — Reciprocal Rank Fusion combines all signals, deduplicates
         │
Output: ranked file results + memories + prior run references
```

Each step is a separate module with a clear interface. For the full details of each step — including SQL queries, Whoosh schema, scoring formulas, and the RRF algorithm — see [search.md](./search.md).

### Key design decisions

- **Query expansion is rule-based, not LLM-powered.** It must be fast (<5ms) and free. Role-specific terms and tag vocabulary matching provide sufficient enrichment for a personal dataset.
- **Metadata pre-filtering uses PostgreSQL array operators.** The `tags && ARRAY[...]` overlap operator with a GIN index narrows 500+ files to ~30–100 candidates before Whoosh runs.
- **Whoosh `content` field is not stored.** The index tracks which words appear in which files but does not duplicate the text. Content is loaded from vault files by the Context Assembler, keeping the index small (~5 MB for 500 files).
- **Reciprocal Rank Fusion (RRF)** combines rankings from multiple sources. It is score-scale-independent, making it robust when combining BM25 scores with metadata signals and (later) semantic similarity scores.
- **Chunking is section-level at H2 boundaries** for files exceeding ~2,500 tokens. Each chunk carries cascading metadata from the heading hierarchy (per HiQA research). Files under 2,000 tokens are retrieved whole — chunking adds overhead without benefit at this size.

### Performance characteristics

| Metric | Phase 1 (current) | Phase 2 (target) | Phase 3 (future) |
|---|---|---|---|
| **Query time (500 files)** | ~200ms | <50ms | <100ms (no rerank) |
| **Index build time** | N/A | ~1s for 500 files | Same + embedding time |
| **Incremental update** | N/A | ~10ms per file | ~10ms + embedding API call |
| **Index size** | None | ~5 MB | ~5 MB + ~50 MB (pgvector) |
| **Memory usage** | ~5 MB | ~20 MB | ~25 MB |

For a personal dataset, all phases complete well within acceptable latency. The bottleneck is always LLM inference, not search.

### Future: semantic search (pgvector)

Keyword search only finds documents containing the exact search terms. Semantic search (pgvector) finds documents by **meaning** — "data protection approaches" matches "privacy compliance framework" even though no keywords overlap. The two methods are complementary: BM25 catches exact terms that embeddings miss; embeddings catch conceptual matches that BM25 misses. Whoosh stays even after pgvector is added, and serves as a fallback when the embedding API is unavailable. See [search.md — Semantic Search](./search.md#semantic-search-with-pgvector-phase-3--design-notes) for the full design.

---

## How All Three Components Interact (complete flow)

Here is the full data flow when the Orchestrator handles a request:

```
 ORCHESTRATOR                         DATA LAYER
      │
      │  "Find stalled Trello tasks"
      │  context: work
      │
      │  ──── Context Assembler asks Search Algorithm ────>
      │
      │                    SEARCH ALGORITHM
      │                         │
      │           Step 1: Extract search terms
      │              ["stalled", "tasks", "Trello", "triage"]
      │                         │
      │           Step 2: Query PostgreSQL (file_index)
      │              → filter by context='work' and tags
      │              → 47 candidate files
      │                         │
      │           Step 3: Query Whoosh index
      │              → score candidates by relevance
      │              → top 10 results with scores
      │                         │
      │           Step 4: Query PostgreSQL (memories)
      │              → "User's work Trello board is 'Work Q1'"
      │              → "User prefers bullet-point format"
      │                         │
      │           Step 5: Query PostgreSQL (runs)
      │              → Similar request 3 days ago, used task-triage.md
      │                         │
      │           Step 6: Rank and return
      │                         │
      │  <──── Returns ranked results ────
      │
      │  Context Assembler loads file content:
      │  ──── Read from User Dataset (files) ────>
      │
      │           USER DATASET
      │              → Read prompts/secretary.md (P0)
      │              → Read policies/tools-allowlist.md (P0)
      │              → Read workflows/task-triage.md (P1)
      │              → Read knowledge/work/trello-conventions.md (P1)
      │
      │  <──── File contents returned ────
      │
      │  Context Assembler packs everything into
      │  the token-budgeted context package
      │  → sends to Agent Runner
```

---

## Configuration

Data layer configuration lives in the Orchestrator's `config.yaml`, which is **external to the code repository**. The Harle repo provides a `config.example.yaml` template that users copy and customize for their deployment.

Every path and connection string points to external resources — nothing references locations inside the Harle code repository:

```yaml
dataset:
  path: "/home/user/harle-vault"       # Path to the vault directory (EXTERNAL)
  sync_interval_seconds: 300           # Re-sync every 5 minutes
  sync_on_request: true                # Also check for changes before each request
  file_extensions: [".md", ".txt"]     # File types to index
  ignore_patterns: [".git/*", "*.tmp"] # Paths to skip

search:
  max_results: 10                      # Max files returned per query
  title_boost: 2.0                     # Relevance multiplier for title matches
  tag_boost: 1.5                       # Relevance multiplier for tag matches
  recency_weight: 0.2                  # How much to favor newer files (0-1)
  min_score: 0.1                       # Minimum relevance score to include

indexer:
  database_url: "postgresql+asyncpg://harle:***@localhost:5432/harle"  # External DB
  summary_model: "gpt-4o-mini"         # Model used for auto-generating summaries
  auto_summarize: true                 # Generate summaries for new files
  embedding_model: "text-embedding-3-small"  # For future semantic search
```

**Environment variable overrides** (useful for Docker and CI):

| Config key | Environment variable | Example |
|---|---|---|
| `dataset.path` | `HARLE_DATASET_PATH` | `/data/vault` |
| `indexer.database_url` | `DATABASE_URL` | `postgresql+asyncpg://harle:pass@db:5432/harle` |

All data paths are user-configurable. Two users running the same Harle codebase simply point `dataset.path` at their own vaults and `database_url` at their own databases.

---

## Error Handling

| Error | What happens | User impact |
|---|---|---|
| **File not found** | `file_index` row is marked as deleted on next sync. Search excludes it. | None — result just will not include the missing file. |
| **Database unreachable** | Search falls back to Whoosh-only mode (no metadata filtering, no memories, no prior runs). | Slightly lower search quality. Warning included in the run log. |
| **Whoosh index corrupted** | Index is rebuilt from scratch on next startup. Takes ~1 second for 500 files. | Momentary delay on restart. No data loss (index is rebuilt from files). |
| **File encoding error** | File is skipped during indexing. Warning logged. | That file will not appear in search results until the encoding is fixed. |
| **Dataset too large for sync** | Only changed files are re-indexed (hash-based). Full re-index only on first startup. | No impact on normal operation. First startup may take a few seconds longer. |

---

## Project Structure (Python, inside the Harle code repository)

The Data Layer **code** (readers, writers, search engine, indexer) lives inside the Orchestrator's Python project in the Harle code repository. The **data** it operates on (vault files, database rows) is external.

```
harle/src/harle/              ← Code (in this repository)
│
├── dataset/                     # User Dataset interface
│   ├── reader.py               # Read files, parse frontmatter, load content
│   ├── writer.py               # Write files (with approval checks)
│   ├── sync.py                 # Git pull, hash-based change detection
│   └── frontmatter.py          # YAML frontmatter parser
│
├── search/                      # Search Algorithm
│   ├── engine.py               # Main search orchestration (the 6-step pipeline)
│   ├── whoosh_index.py         # Whoosh index build, update, query
│   ├── query_expander.py       # Extract and expand search terms from requests
│   ├── ranker.py               # Combine scores from multiple sources, re-rank
│   └── types.py                # SearchResult, SearchQuery data classes
│
├── db/                          # Indexer (PostgreSQL)
│   ├── connection.py           # Connection pool management (asyncpg)
│   ├── models.py               # SQLAlchemy table definitions
│   ├── file_index.py           # file_index CRUD operations
│   ├── runs.py                 # runs CRUD operations
│   ├── artifacts.py            # artifacts CRUD operations
│   ├── memories.py             # memories CRUD operations
│   ├── conversations.py        # conversations + messages CRUD
│   └── embeddings.py           # embeddings CRUD (future, stub for now)
│
└── indexing/                    # Sync pipeline (dataset → Indexer + Whoosh)
    ├── indexer.py              # Main sync orchestration
    ├── hasher.py               # SHA-256 hash computation for change detection
    └── summarizer.py           # Auto-generate file summaries via LLM
```

**Key dependencies (in addition to the Orchestrator's):**

| Package | Purpose |
|---|---|
| `whoosh` | Full-text search index (build, update, query) |
| `sqlalchemy` + `asyncpg` | PostgreSQL access (shared with Orchestrator) |
| `python-frontmatter` | Parse YAML frontmatter from Markdown files |
| `tiktoken` | Estimate token counts for files (shared with Orchestrator) |

---

## Technology Choices Summary

| Decision | Choice | Key reason |
|---|---|---|
| **File format** | Markdown with YAML frontmatter | Human-readable, version-controlled, structured enough for search |
| **File sync** | Git (primary), Syncthing (alternative) | Familiar, conflict-aware, full history |
| **Database** | PostgreSQL 16+ with pgvector | One DB for structured data, metadata, vectors, and logs |
| **Full-text search** | Whoosh | Pure Python, no external service, fast for personal scale |
| **Semantic search** | pgvector (future) | Stays inside Postgres, no separate service |
| **Change detection** | SHA-256 content hashing | Fast, accurate, platform-independent |
| **File summaries** | GPT-4o-mini (auto-generated) | Cheap, improves search relevance |
| **ORM** | SQLAlchemy (async) | Shared with Orchestrator, industry standard |
| **Frontmatter parser** | python-frontmatter | Lightweight, well-maintained, standard format |
