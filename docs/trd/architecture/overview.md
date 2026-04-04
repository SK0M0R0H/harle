---
title: "Harle Architecture Description"
tags: [architecture, overview, components, connections, import, deployment, infrastructure, technology-stack]
context: global
last_updated: 2026-03-01
summary: "Describes the overall architecture of Harle, its main components (including the Connections Layer and Import Module Layer), technology choices, deployment strategy, and security approach."
---

# Harle Architecture Description

> Harle is a personal AI assistant system that feels like a small team of reliable assistants, operating over your own data with your rules, your integrations, and a memory you control.

This document describes the architecture of Harle, explains every component and its role, and justifies the technology choices. It is written for someone who may not have deep backend experience.

---

## Architecture Overview

The system consists of several main components connected in a pipeline. Inside the Orchestrator, a **Connections Layer** provides shared API clients and credentials for external services; both the **Tool Module Layer** and the **Import Module Layer** use it so that each external product (Notion, Trello, Miro, Tavily, etc.) is configured once. The diagram below mirrors the `scheme.png` reference architecture:

```
┌─────────────┐     ┌──────────────────────────┐     ┌────────────────┐     ┌──────────────────────────┐
│  Interface   │────>│     Orchestrator          │────>│  Models/Agents │────>│  Tool Module Layer       │
│  (CLI first) │     │  (Connection Registry,   │     │                │     │  (Web Search, Trello...) │
└─────────────┘     │   Tool + Import Registry) │     └───────┬────────┘     └────────────┬─────────────┘
                    └──────────┬───────────────┘              │                           │
                               │                              │     ┌─────────────────────┘
                    ┌──────────▼───────────┐                   │     │
                    │  Search Algorithm   │                   │     │  Import Module Layer
                    │  (not AI)            │                   │     │  (Notion, Miro → vault)
                    └──────────┬───────────┘                   │     │
                               │                              │     │
                    ┌──────────▼───────────┐                   │     │
                    │  Indexer             │<─────────────────┘     │
                    │  (main DB for search)│                         │
                    └──────────┬───────────┘                         │
                               │                                     │
                    ┌──────────▼───────────┐                         │
                    │  Files and Data      │<────────────────────────┴────
                    │  (your dataset)      │
                    └──────────────────────┘
```

**Data flows:**
- The **Interface** sends user requests to the **Orchestrator**.
- The **Orchestrator** decides what to do: it may query the **Search Algorithm** to find relevant data, call **Models/Agents** for reasoning, or invoke tools through the **Tool Module Layer**. It also hosts the **Connection Registry** (shared API clients and credentials) and the **Import Module Layer** (bulk import from external sources into the vault).
- The **Search Algorithm** uses the **Indexer** (database) to find relevant content from **Files and Data**.
- **Models/Agents** can read from and write to both the **Indexer** and **Files and Data**.
- **Tool Modules** (e.g. Web Search, Trello) and **Import Sources** (e.g. Notion, Miro) obtain authenticated API clients from the **Connections Layer** — each external service is configured once and reused. Tool modules and import modules can read from and write to **Files and Data**.

---

## Key Architectural Principle: Data Lives Outside the Code Repository

**This repository contains the Harle application — code, configuration templates, and documentation. It does not contain any user data.** All user-specific data is stored externally and referenced by configurable paths:

| What | Where it lives | Why |
|---|---|---|
| **Application code** (orchestrator, CLI, tools) | This repository (`harle`) | Shared across all users. Version-controlled as software. |
| **Architecture docs, config templates** | This repository (`harle`) | Describe and configure the system. Templates are copied and customized per deployment. |
| **User Dataset** (Markdown vault) | Separate directory or Git repository (e.g. `~/harle-vault`) | Each user has their own rules, prompts, knowledge, and preferences. The vault is personal. |
| **Database state** (PostgreSQL data) | External PostgreSQL instance (Docker volume, managed DB, etc.) | Run logs, memories, embeddings, and conversation history are per-user runtime state. |
| **Runtime configuration** (`config.yaml`) | Outside the repo (e.g. `~/.config/harle/config.yaml`, Docker volume, or env vars) | Contains paths, secrets, and per-deployment settings. A `config.example.yaml` template is provided in the repo. |

**Why this separation matters:**

1. **Multi-user customization.** Different users clone or fork the same Harle repository and point it at their own vault and database. The code is identical; the data is personal.
2. **Clean version control.** The application repository tracks code changes. User data (which changes constantly — new notes, new run logs, new memories) has its own versioning lifecycle (the vault's own Git repo).
3. **Security.** Secrets, personal knowledge, and API keys never end up in the application repository — even accidentally.
4. **Reproducibility.** A fresh clone of this repository is a working Harle installation once you provide a vault path, a database connection, and an API key. No data migration, no state cleanup.
5. **Portability.** You can upgrade Harle (pull new code) without touching your data. You can migrate your data (move your vault to a new machine) without touching the code.

**In practice, a Harle deployment looks like this:**

```
Your machine / server
│
├── ~/projects/harle/              ← This repository (application code)
│   ├── src/harle/                 ← Python orchestrator
│   ├── harle-cli/                 ← Go CLI
│   ├── docs/                      ← Architecture docs
│   ├── config.example.yaml        ← Template configuration
│   └── docker-compose.yml         ← Deployment template
│
├── ~/harle-vault/                 ← User dataset (separate Git repo)
│   ├── prompts/
│   ├── policies/
│   ├── knowledge/
│   └── ...
│
├── ~/.config/harle/
│   └── config.yaml                ← Runtime configuration (not in any repo)
│
└── /var/lib/postgresql/           ← Database storage (Docker volume or system)
    └── harle/                     ← PostgreSQL data directory
```

This separation is enforced at every level: the `.gitignore` excludes data directories, the configuration uses external paths, and Docker Compose mounts data as volumes.

---

## Component Details

### 1. Interface (CLI first)

**What it does:** This is how you talk to Harle — the "front door" of the system. You launch it, enter a session, and communicate with Harle until you explicitly quit — like launching a Python shell or `psql`.

**Important architectural note:** The CLI is a **thin client**. It does not run any AI logic, load any models, or process data. All it does is send your messages over the network to the Orchestrator (via an HTTP/REST API), stream back responses, and handle interactive flows (clarifications, approvals). This means the CLI has no dependency on AI/ML libraries.

**Session-first interaction model:**

The CLI is always session-based. Running `harle` drops you into an interactive session. Every message you type is part of that session — the Orchestrator keeps full conversation history, so follow-up questions work naturally. To start a fresh session, you explicitly type `/quit` or `/new`. This is analogous to how `python`, `node`, or `psql` work: you enter the shell, interact, and leave when done.

```
$ harle --context=work
harle> Find stalled tasks in Trello
[secretary] Found 7 stalled tasks...
harle> Reformulate the first one       ← context carries over
[secretary] Here are options: ...
harle> /quit
Session saved.
```

For scripting and automation, `harle exec "..."` runs a single task non-interactively (no session, no prompt) and exits — the escape hatch for shell scripts and pipelines.

**Why CLI first:**
- **Simplest to build.** A CLI has no buttons, no styling, no browser. You focus on the logic, not the look.
- **Developer-friendly.** You are already using a terminal (e.g. in Cursor). A CLI fits naturally into that workflow.
- **Easy to extend later.** Once the CLI works, you can add a web chat UI, a Telegram bot, or a Slack integration on top — they all just send the same request to the Orchestrator's API.

**Technology: Go with [Cobra](https://cobra.dev/) + [Bubbletea](https://github.com/charmbracelet/bubbletea)**

Since the CLI is a thin HTTP client, the language choice is **independent** from the server side. The server (Orchestrator) is written in Python because of the AI/ML ecosystem, but the CLI has no AI dependencies — it only sends JSON over HTTP and renders the response.

**Why Go:**
- **Single binary.** `go build` produces one executable file with zero dependencies. You copy it to any machine (Linux, macOS, Windows, even a phone via Termux) and it works. No runtime, no `pip install`, no virtual environments.
- **Fast startup.** Go binaries start in ~10ms. For a tool you launch many times a day, this feels instant — compared to ~200–500ms for a Python CLI that has to load an interpreter.
- **Industry standard for CLI tools.** Docker, Kubernetes (`kubectl`), GitHub CLI (`gh`), Terraform, and Hugo are all written in Go. The ecosystem for building CLI tools in Go is mature and well-documented.
- **Easy cross-compilation.** One command builds the binary for any OS/architecture: `GOOS=linux GOARCH=arm64 go build`. This is useful for deploying to different machines.

**Why not Python for the CLI:**
The server is Python, but that does not mean the CLI should be too. The CLI talks to the server via a simple HTTP API (JSON in, JSON out) — there is no shared business logic, no imported modules. The only cost of using a different language is maintaining a small API contract (a few JSON request/response schemas), which is trivial. The benefits (single binary, fast startup, easy distribution) far outweigh this.

For the full CLI architecture (session management, commands, rendering, project structure), see [cli.md](./cli.md).

**Future interfaces** (not in the first version):
- Web chat UI (e.g. using a lightweight React/Next.js app or Streamlit)
- Telegram bot
- Slack / Discord integration
- Mobile access via any of the above

All future interfaces connect to the same Orchestrator API, so they are independent from each other and from the CLI.

---

### 2. Orchestrator (scripts + agent logic)

**What it does:** The Orchestrator is the "brain" of Harle. When you send a request, the Orchestrator decides:
- What kind of task is this?
- Which agent (role) should handle it?
- Does it need clarification before proceeding?
- What data should be retrieved from your dataset to help the agent?
- What tools (Trello, GitHub, etc.) are needed?

It coordinates the entire workflow from input to output.

**Technology: Python service using [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) (code-first, Option A from the proposal)**

**What is the OpenAI Agents SDK?**  
It is an open-source Python library from OpenAI that lets you define "agents" — roles with specific instructions, tools, and guardrails. You write the orchestration logic in Python, giving you full control. It is **not** a no-code tool — you write actual code, which means you can customize everything.

**Why OpenAI Agents SDK:**
- **Maximum control.** You decide exactly what happens at each step. There is no "magic" — every decision is in your code.
- **Clean logging.** Every run produces a structured log (what was asked, what was decided, what tools were called, what was returned). This is critical for debugging and trust.
- **Best path to open-source models.** The SDK talks to OpenAI now, but the model calls go through a clean interface. Later, you can swap OpenAI for a self-hosted model (like Llama or Mistral) without rewriting the orchestrator.
- **MCP support.** The SDK supports Model Context Protocol (MCP), a standard way to connect tools. This means integrations you build today will work even if you switch orchestrators later.
- **Active development.** OpenAI actively maintains this SDK, and it aligns with the latest model capabilities.

**What the Orchestrator does step by step:**
1. **Receives** a request from the Interface.
2. **Clarifies** — if the request is vague, it asks 1–3 targeted questions before proceeding.
3. **Retrieves** — it searches your dataset (via the Search Algorithm) for relevant context: your rules, prior decisions, preferences, related notes.
4. **Routes** — it picks the right agent role (Researcher, Secretary, Specialist) based on the task.
5. **Executes** — the chosen agent calls the LLM with all the context, possibly using tools.
6. **Stores** — results are saved to your database and files.
7. **Returns** — the final output goes back to the Interface.

**Connections Layer (inside the Orchestrator):**  
The Orchestrator owns a **Connection Registry** that holds configured, authenticated clients for every external service (Notion, Trello, Miro, Tavily, etc.). Credentials and API client setup live in a single `connections` section of `config.yaml`. The Tool Module Layer and the Import Module Layer look up connections by name instead of each defining their own API keys and clients. This avoids duplicate configuration, shared rate limiting across tools and import, and a single place to run health checks (e.g. `harle connections status`). For the full design, see **[connections.md](./connections.md)**.

**Why not n8n, Dify, or other alternatives:**
- **n8n** (Option B in the proposal) is great for recurring workflows with many connectors, but adds a dependency on a separate UI server and is harder to customize for complex agent logic.
- **Dify** (Option C) is a low-code platform — fast to start but risks vendor lock-in and limits customization.
- The code-first approach is recommended by the proposal as the "best long-term foundation" (Option A).

---

### 3. Search Algorithm (not AI)

**What it does:** Before an agent starts working, the Orchestrator needs to find relevant information from your dataset. The Search Algorithm is responsible for finding the right files, notes, and prior decisions — **without using AI**. It uses traditional search techniques that are fast, deterministic, and predictable.

**Technology: Combination of [Whoosh](https://whoosh.readthedocs.io/) (full-text search) + keyword/tag matching in Python**

**What is full-text search?**  
Imagine you have 500 Markdown files in your dataset. You want to find all files that mention "privacy" and "L2 architecture". Full-text search builds an index (like the index at the back of a book) that lets you find matches instantly, without reading every file.

**The core problem this component solves — context window limitations:**

Every language model has a **context window** — a hard limit on how much text it can process in a single request. Think of it as the model's "working memory." As of early 2026, typical context windows are:

| Model | Context window | Roughly equivalent to |
|---|---|---|
| GPT-4o | ~128k tokens | ~300 pages of text |
| GPT-4o-mini | ~128k tokens | ~300 pages of text |
| Open-source models | 8k–32k tokens | ~20–80 pages of text |

This sounds like a lot, but your dataset can easily exceed it. If you have 500 Markdown files averaging 2 pages each, that is ~1,000 pages — **3–50x larger than any model can read at once**. And as your dataset grows (years of notes, decisions, project files, Trello exports), this gap only widens.

**You cannot just feed the entire dataset to the model.** Even if a model's context window were unlimited, sending everything would be:
- **Slow** — processing more text takes more time.
- **Expensive** — LLM APIs charge per token. Sending your entire dataset on every request would cost dollars instead of cents.
- **Noisy** — the more irrelevant text you include, the worse the model performs. Models get "distracted" by irrelevant context and produce lower-quality answers.

**This is why the Search Algorithm exists.** Its job is to **reduce the entire dataset down to the few most relevant pieces** before anything reaches the model. Instead of sending 1,000 pages, the search finds the 5–10 pages that actually matter for the current request. The model gets a focused, relevant context — and gives a better answer.

This is the "prepare data for agent" step from the architecture diagram.

**Why a non-AI search algorithm (instead of using AI for search too):**
- **It can handle the full dataset.** Traditional search indexes your entire dataset once and queries it in milliseconds. There is no context window — the index covers everything, no matter how large.
- **Speed.** Traditional search returns results in milliseconds. An AI-based search (e.g. sending chunks to the LLM to rank) would take seconds per query and still be limited by the context window.
- **Predictability.** You get exactly the documents that match your query. There is no "hallucination" — the search either finds a match or it does not.
- **Cost.** It runs locally, for free, with no API calls. Using AI for search would multiply your LLM costs.
- **Independence from models.** The search works even if the LLM API is down, slow, or being swapped for a different provider.

**Why Whoosh:**
- **Pure Python.** No external services to install or manage. It runs inside your Python process.
- **Lightweight.** Perfect for a personal dataset (hundreds to low thousands of files).
- **Good enough to start.** Later, if your dataset grows very large, you can replace Whoosh with Elasticsearch or Meilisearch without changing the rest of the system.

**How it works with the Indexer:**  
Whoosh handles keyword/full-text search. The Indexer (PostgreSQL with pgvector) will later add **semantic search** — finding documents by meaning, not just keywords. For example, searching for "privacy solutions" might also return a document titled "data protection approaches" even though the exact words do not match. Both search methods feed into the same pipeline: reduce the dataset to a small, relevant subset, then hand that subset to the model.

**The pattern in summary:**

```
Your full dataset (1,000+ pages)
         │
    Search Algorithm
    (scans everything,
     no context window limit)
         │
         ▼
  Top 5–10 relevant pages
         │
    Fits inside the model's
    context window
         │
         ▼
   Model produces a high-quality,
   focused answer
```

---

### 4. Indexer (main DB for search)

**What it does:** The Indexer is the main database that stores structured information about your dataset, agent runs, search indices, and metadata. It is the "source of truth" for everything that happens in Harle.

**Technology: [PostgreSQL](https://www.postgresql.org/) with [pgvector](https://github.com/pgvector/pgvector) extension**

**What is PostgreSQL?**  
PostgreSQL (often called "Postgres") is the most popular open-source relational database. Think of it as a very powerful, very reliable spreadsheet system — but designed for millions of rows, complex queries, and concurrent access.

**What is pgvector?**  
pgvector is a PostgreSQL extension that adds the ability to store and search "vector embeddings." A vector embedding is a list of numbers that represents the meaning of a piece of text. Two texts with similar meaning will have similar vectors. This enables **semantic search** — finding documents by meaning, not just by keywords.

**Why PostgreSQL:**
- **Industry standard.** Postgres is used by companies of all sizes, from startups to Fortune 500. This means excellent documentation, community support, and tooling.
- **One database for everything.** Instead of running separate databases for structured data, search, and vectors, Postgres (with pgvector) handles all three. This dramatically simplifies operations.
- **Reliable and battle-tested.** Postgres has been in active development for over 30 years. It handles crashes, concurrent writes, and data integrity automatically.
- **Easy to run.** A single `docker-compose up` command starts a Postgres instance with pgvector. No cloud account needed.
- **Recommended by the proposal.** The proposal explicitly recommends Postgres as the source of truth for tasks, runs, artifacts, and audit logs.

**What the Indexer stores:**

| Table / Purpose | What it contains | Example |
|---|---|---|
| `runs` | Log of every Orchestrator execution | "User asked X, agent Y ran, result was Z" |
| `artifacts` | Outputs produced by agents | A research report, a status summary |
| `memories` | Key decisions and preferences | "User prefers bullet-point format" |
| `file_index` | Metadata about files in the dataset | File path, tags, last modified, summary |
| `embeddings` | Vector representations for semantic search | pgvector column for similarity queries |

**Why not SQLite, MongoDB, or a dedicated vector DB?**
- **SQLite** is great for single-user apps but struggles with concurrent access (e.g. if you run agents in parallel) and has no vector extension.
- **MongoDB** is a document database — flexible but harder to query for relational data (like "find all runs where agent X used tool Y"). Postgres handles both structured and unstructured data well.
- **A dedicated vector DB** (like Pinecone or Weaviate) would mean running a separate service just for embeddings. pgvector keeps everything in one place, which is simpler to manage and cheaper to operate.

---

### 5. Models / Agents

**What it does:** This is where the actual AI reasoning happens. When the Orchestrator decides that a task needs intelligence (writing, analyzing, summarizing, planning), it sends a request to a language model. "Agents" are specific roles with specific instructions — they are not separate programs, they are configurations that tell the model how to behave.

**Technology: [OpenAI API](https://platform.openai.com/docs/) (GPT-4o, GPT-4o-mini) now, self-hosted open-source models later**

**What is a model provider?**  
A model provider is a service that hosts a large language model (LLM) and exposes it via an API. You send text in, you get text out. Think of it like a very smart text-processing service.

**Why OpenAI to start:**
- **Best quality today.** As of early 2026, OpenAI models consistently rank among the top for reasoning, writing, and tool-use tasks.
- **Easiest to start with.** One API key, well-documented SDK, and you are running in minutes.
- **Reliable.** High uptime, fast responses, and a mature API.
- **Cost-effective for personal use.** GPT-4o-mini is very cheap for routine tasks; GPT-4o handles complex reasoning when needed.

**Why the plan to migrate to open-source models later:**
- **Privacy.** With a self-hosted model, your data never leaves your machine.
- **Cost at scale.** If you run many requests per day, self-hosting can be cheaper.
- **Independence.** No dependency on a vendor's pricing changes or policy updates.

**How migration will work:**  
The Orchestrator calls models through a single internal interface (a "provider wrapper"). Today that wrapper talks to OpenAI. Later, you point it at a self-hosted server running an OpenAI-compatible API (e.g. [vLLM](https://docs.vllm.ai/), [Ollama](https://ollama.com/), or [llama.cpp](https://github.com/ggerganov/llama.cpp)). The rest of the system does not change.

**Agent roles planned for Harle:**

| Role | What it does | Tools it can use |
|---|---|---|
| **Researcher** | Searches the web and dataset, synthesizes findings into reports | Internet search, dataset read, file write |
| **Secretary** | Manages tasks, summarizes, organizes daily workflow | Trello, dataset read/write, chat |
| **Specialist** | Optimizes the Harle system itself, improves prompts and dataset | Dataset read/write, agent logs, versioning |

---

### 6. Tool Module Layer (Web Search + Trello from day one)

**What it does:** The Tool Module Layer is how Harle acts on the outside world. It is the modular, extensible system for all capabilities — web search, Trello, script execution, vault management, and future additions. Each capability is a **tool module**: a self-contained directory with a Python class, tool functions, optional domain knowledge (skills), and configuration.

**Technology: Python tool modules with a central Tool Registry, bridged to [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) `FunctionTool` objects. Optional [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) compatibility for interoperability.**

For the full architecture — the `BaseToolModule` interface, the Tool Registry, tool skills, the security model, MCP compatibility, configuration, and the incremental implementation plan — see **[tools.md](./tools.md)**.

**Key design principles:**
- **Tool functions are the single source of truth.** Each tool is a plain Python function with type hints and a docstring. The registry introspects these to generate JSON schemas for the LLM — no separate schema files, no decorators, no duplication.
- **Modules group related tools.** All Trello operations live in `TrelloModule`, all web search operations in `WebSearchModule`. Each module handles its own lifecycle (init, shutdown, health check) and configuration. Modules that access external APIs receive an authenticated client from the **Connections Layer** (see [connections.md](./connections.md)) instead of managing their own credentials or HTTP clients.
- **Config-driven.** Each module is enabled/disabled and configured in `config.yaml`; API-accessing modules reference a connection by name (`connection: trello`), with credentials living in the shared `connections` section. Operation modes (`read_only`, `propose`, `auto`) control approval behavior per module. Security constraints (allowlists, blocklists, path restrictions) protect tools with local system access.
- **Skills inject domain knowledge.** Each module can include Markdown files that teach the LLM *how* to use the tools effectively — usage patterns, conventions, safety rules. Which skills are active is controlled by config, and users can override built-in skills from their vault.
- **MCP is an optional layer.** Internally, modules communicate with the Orchestrator through in-process Python calls (fast, simple). Modules can optionally be exported as MCP servers for use by Cursor, Claude, or other clients. External MCP servers can be imported through an adapter.

**First modules (Web Search + Trello):**

| Module | Role | Why from day one |
|---|---|---|
| **Web Search** | `search_web`, `search_news`, `fetch_page` via Tavily/Bing/SearXNG | Every agent role needs live information. Read-only, low risk. Transforms Harle from "smart notes" to an actual research tool. |
| **Trello** | `search_cards`, `create_card`, `move_card` via Trello API | Immediate value for task management. Simple API, low risk. Safety-first rollout: read-only → propose → auto. |

**Planned modules:**

| Module | Use case | Priority |
|---|---|---|
| **Vault** | Read/write notes, search the user dataset | High — needed for all roles |
| **Scripts** | Execute user scripts on the host (with security sandbox) | Medium |
| **GitHub** | Read PRs, summarize changes, propose review comments | High |
| **Notion** | Read/write research documents, store reports | Medium |
| **Calendar** | Schedule-aware task planning | Medium |

---

### 7. Import Module Layer (external data into the vault)

**What it does:** The Import Module Layer is how external knowledge enters Harle's awareness. When you import data from Notion, Miro, Trello, bookmarks, or other sources, the call goes through an import module. Data can be **fully materialized** into the vault as Markdown files or stored as **reference files** (lightweight metadata plus access instructions so the agent can fetch live data via a tool at runtime). Import is triggered from the CLI (`harle import notion ...`) or on a schedule, not during agent reasoning.

**Technology: Python import sources with a central Import Registry, conversion pipeline, and Vault Writer. Shares the Connections Layer with the Tool Module Layer.**

For the full architecture — the `BaseImportSource` interface, the Import Registry, full vs. reference materialization, the conversion pipeline, and configuration — see **[import_module.md](./import_module.md)**.

**Key points:**
- **Same connections as tools.** Import sources that use an API (e.g. Notion API mode, Miro) look up their connection from the same Connection Registry as the tool modules. Credentials are configured once in `config.yaml` under `connections`; both the Notion tool module and the Notion import source use the same `NotionConnection`.
- **File-mode sources need no connection.** Notion ZIP export, bookmarks HTML, and similar file-based imports work without any API credentials — useful for onboarding before setting up tokens.
- **Reference imports bridge to tools.** Large or dynamic sources (e.g. a Notion database with hundreds of rows) can be imported as reference files: the vault stores metadata and `access_via` / `access_params` so the agent knows which tool to call for live data.

---

### 8. Files and Data (your dataset)

**What it does:** This is your personal knowledge base — the collection of Markdown files, notes, rules, prompts, and documents that Harle operates over. It is the "ground truth" that agents refer to when making decisions.

**Critical: the dataset is NOT part of the Harle code repository.** It lives in its own directory (or its own Git repository) outside the application code. Harle reads the dataset path from configuration (`dataset.path` in `config.yaml` or the `HARLE_DATASET_PATH` environment variable). This means every user has their own vault with their own rules, prompts, and knowledge — while sharing the same Harle codebase.

**Technology: Plain Markdown files in an [Obsidian](https://obsidian.md/)-style vault, stored in a separate Git repository or directory, synced via Git or [Syncthing](https://syncthing.net/)**

**What is an Obsidian-style vault?**  
It is simply a folder of Markdown files organized in directories. Obsidian is a popular note-taking app that uses this format, but you do not need Obsidian — any text editor works. The key idea is that your data is **plain files**, not locked inside a proprietary database.

**Why Markdown files:**
- **Human-readable.** You can open, read, and edit any file with any text editor. No special tools required.
- **Version-controlled.** Put the vault in its own Git repository and you get full history: who changed what, when, and why.
- **Portable.** If Harle stops working tomorrow, your data is still usable. It is just text files.
- **Searchable.** Both traditional search (grep, Whoosh) and AI-based search work well on Markdown.

**Why a separate Git repository for the vault (not the same repo as the code):**
- **Different lifecycle.** Application code changes with features and bug fixes. Your vault changes every day as you add notes, update workflows, and agents write logs. These are independent versioning streams.
- **Multi-user support.** The Harle code repo is shared (everyone runs the same application). Each user's vault is personal and private.
- **Clean separation.** You can `git pull` a Harle update without merge conflicts against your personal notes. You can push your vault to a private Git remote without exposing the Harle codebase.
- **Different access controls.** The code repo may be public or shared with collaborators. The vault contains personal and potentially sensitive data.

**Alternative: Syncthing** for real-time sync without commits. Useful if you want automatic, seamless sync between two computers without thinking about Git operations.

**Vault structure (recommended):**

```
~/harle-vault/                    ← Separate directory or Git repo, NOT inside Harle code
├── prompts/              # Instructions for each agent role
│   ├── researcher.md
│   ├── secretary.md
│   └── specialist.md
├── policies/             # Rules and constraints
│   ├── privacy.md
│   ├── tools-allowlist.md
│   └── approval-rules.md
├── workflows/            # Step-by-step workflow templates
│   ├── weekly-status.md
│   ├── product-hypothesis.md
│   └── task-triage.md
├── knowledge/            # Your personal knowledge base
│   ├── work/             # Work-related notes (separate context)
│   └── personal/         # Personal notes (separate context)
├── examples/             # Example inputs/outputs for agents
│   └── good-goals.md
└── logs/                 # Agent run summaries (auto-generated)
    └── 2026-02/
```

---

## Infrastructure & Deployment

### How it all runs together

**Technology: [Docker Compose](https://docs.docker.com/compose/) on a small VPS or home server**

**What is Docker?**  
Docker is a tool that lets you run applications in isolated containers — think of them as lightweight, portable mini-computers. Each container has exactly what it needs (code, libraries, settings) and nothing more.

**What is Docker Compose?**  
Docker Compose lets you define multiple containers in one file and start them all with a single command. For Harle, one command starts everything: the orchestrator, the database, and any other services.

**Why Docker Compose:**
- **Reproducible.** The same `docker-compose.yml` file works on any machine. No "it works on my computer" problems.
- **Easy to start.** One command: `docker-compose up`. One command to stop: `docker-compose down`.
- **Isolates dependencies.** Postgres runs in its own container. The orchestrator runs in its own. They do not interfere with each other.
- **Standard in the industry.** Nearly every modern project uses Docker for deployment.

**Data is mounted, not baked in.** Docker Compose uses volumes to mount external data into containers. The Harle code lives in the container image; the user's vault, database storage, and configuration are mounted from the host machine. This means the same Docker image works for any user — only the mounted volumes differ.

```yaml
# Simplified docker-compose.yml (conceptual)
services:
  orchestrator:
    image: harle-orchestrator
    volumes:
      - ${HARLE_DATASET_PATH:-~/harle-vault}:/data/vault:ro    # User's vault (read-only)
      - ${HARLE_CONFIG_PATH:-~/.config/harle}:/etc/harle:ro     # Runtime config
    environment:
      - DATABASE_URL=postgresql+asyncpg://harle:***@db:5432/harle
  db:
    image: pgvector/pgvector:pg16
    volumes:
      - pgdata:/var/lib/postgresql/data    # Persistent DB storage
volumes:
  pgdata:
```

**Deployment options:**

| Option | Cost | Always on? | Best for |
|---|---|---|---|
| **Home mini PC** (e.g. Intel NUC) | ~$200 one-time | Yes, if powered | Maximum privacy, no recurring cost |
| **Small VPS** (e.g. Hetzner, DigitalOcean) | ~$5–15/month | Yes | Accessible from anywhere, reliable |
| **Your laptop** (dev mode) | Free | Only when open | Development and testing |

### Multi-device access

**Technology: [Tailscale](https://tailscale.com/) (private network overlay)**

**What is Tailscale?**  
Tailscale creates a private network between your devices. Your Harle server, your work laptop, and your personal computer can all see each other as if they were on the same local network — but the connection is encrypted and goes over the internet.

**Why Tailscale:**
- **No open ports.** Your Harle server is not exposed to the public internet. Only your authenticated devices can reach it.
- **Zero configuration.** Install Tailscale on each device, log in, done. No router configuration, no firewall rules.
- **Free for personal use.** The free tier supports up to 100 devices.
- **Works everywhere.** Home, office, coffee shop, phone — all connected.

---

## Technology Stack Summary

| Component | Technology | Why this choice |
|---|---|---|
| **Server language** | Python 3.12+ | Dominant in AI/ML, best SDK support |
| **CLI (Interface)** | Go + Cobra + Bubbletea | Session-based REPL, single binary, fast startup |
| **Orchestrator** | OpenAI Agents SDK | Full control, clean logs, MCP support |
| **Search** | Whoosh | Pure Python, no external services, fast |
| **Database** | PostgreSQL + pgvector | One DB for everything, industry standard |
| **Models** | OpenAI API (now), self-hosted (later) | Best quality today, clean migration path |
| **Connections Layer** | Shared Connection Registry (credentials, httpx clients, rate limiters per service) | Single place for external API config; used by both Tool Module Layer and Import Module Layer (see [connections.md](./connections.md)) |
| **Tool Module Layer** | Python tool modules + Tool Registry + OpenAI Agents SDK bridge | Modular, configurable, secure, MCP-compatible; API clients from Connections Layer |
| **Import Module Layer** | Python import sources + Import Registry + conversion pipeline + Vault Writer | Bulk import from Notion, Miro, etc. into vault; shares Connections Layer with tools (see [import_module.md](./import_module.md)) |
| **Web Search** | Tavily or Bing API (now), SearXNG (later) | Fast to integrate, AI-optimized, low cost at personal scale |
| **Data storage** | Markdown files in a separate Git repo (external to this codebase) | Human-readable, version-controlled, per-user |
| **Deployment** | Docker Compose | One command to start everything |
| **Networking** | Tailscale | Private, secure, zero-config |
| **Sync** | Git or Syncthing | Familiar, reliable, conflict-aware |

---

## Security Approach

Harle follows a "secure enough, not paranoid" philosophy:

1. **Data never in the code repository.** User datasets, database state, and runtime configuration live outside the Harle application repo. The `.gitignore` enforces this. The code repo is safe to share or make public without leaking personal data.
2. **Separate contexts.** Work and personal data live in separate directories (or database schemas) with different access rules.
3. **Read-first, write-later.** All tool modules start in read-only or propose mode. Write access is enabled explicitly, per module, with approval gates. Tools with local system access (scripts, vault) are additionally protected by input validation and execution sandboxing (see [tools.md](./tools.md)).
4. **No secrets in the vault or the code repo.** API keys and tokens live in the `connections` section of config (referencing environment variables or a secrets manager), never in Markdown files or committed configuration. Each external service is configured once and reused by both tool modules and import sources (see [connections.md](./connections.md)).
5. **Private network only.** Harle is only accessible over Tailscale — no public ports, no public URLs.
6. **Audit log.** Every agent run is logged: what was asked, what was decided, what tools were called, what was returned. This is how you build trust.
7. **Propose-only mode.** Agents draft results and suggest actions. You approve before anything is executed — especially for work-related tasks.

---

## How It All Fits Together (Example Flow)

Here is a concrete example. You launch Harle and type: *"Find all stalled tasks in Trello and suggest how to reformulate them."*

```
1. You are in a session (launched with 'harle --context=work')
   You type the request at the harle> prompt
   → CLI sends an HTTP POST to the Orchestrator's API
         │
     [network — your machine → server via Tailscale]
         │
         ▼
2. Orchestrator receives the request (on the server)
   → Recognizes this as a "Secretary" task
   → No clarification needed (request is specific)
         │
         ▼
3. Orchestrator calls Search Algorithm
   → Finds your "task-triage.md" workflow template
   → Finds your Trello preferences from the dataset
         │
         ▼
4. Orchestrator calls Trello module (Tool Module Layer)
   → Module uses the shared Trello connection (Connections Layer)
   → Reads all cards from your Trello boards
   → Identifies cards with no activity in 14+ days
         │
         ▼
5. Orchestrator sends context to the LLM (Models/Agents)
   → Prompt: "Here are stalled tasks: [...]. Here is the user's
      triage workflow: [...]. Suggest reformulations."
   → LLM returns suggestions
         │
         ▼
6. Results are stored
   → Run log saved to Indexer (PostgreSQL)
   → Output saved to Files and Data (Markdown file in vault)
         │
         ▼
7. Response streams back over the network to your CLI
   → CLI renders the suggestions in real-time
   → Session stays open — you can type a follow-up:
     harle> "Reformulate the first one and create a Trello card"
```

---

## What Comes Next

This architecture is designed to grow. The first version focuses on:

1. **CLI interface** — talk to Harle from the terminal
2. **One agent role** (Secretary) — the most immediately useful
3. **Connections Layer** — shared API clients and credentials for external services (see [connections.md](./connections.md)); initialized before tools and import
4. **Tool Module Layer** — Web Search (first module) + Trello, with the registry, skills, and security layers; modules obtain API clients from the Connections Layer (see [tools.md](./tools.md) for the incremental plan)
5. **Import Module Layer** — bulk import from Notion, Miro, etc. into the vault, sharing the same connections as the tool modules (see [import_module.md](./import_module.md))
6. **Markdown dataset** — your knowledge base
7. **PostgreSQL** — logging and search index
8. **OpenAI models** — for reasoning

Once this loop works reliably, the next steps are:
- Add Researcher and Specialist roles
- Add more tool modules (vault, scripts, Notion) and import sources following the same pattern
- Enable write tools with approval gates
- Add semantic search (pgvector)
- Deploy to a VPS for always-on access
- Add Telegram bot as primary interface (see [telegram_bot.md](./telegram_bot.md))
