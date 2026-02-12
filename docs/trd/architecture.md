# Harle Architecture Description

> Harle is a personal AI assistant system that feels like a small team of reliable assistants, operating over your own data with your rules, your integrations, and a memory you control.

This document describes the architecture of Harle, explains every component and its role, and justifies the technology choices. It is written for someone who may not have deep backend experience.

---

## Architecture Overview

The system consists of six main components connected in a pipeline. The diagram below mirrors the `scheme.png` reference architecture:

```
┌─────────────┐     ┌──────────────────────────┐     ┌────────────────┐     ┌──────────────────────────┐
│  Interface   │────>│     Orchestrator          │────>│  Models/Agents │────>│  External Integrations   │
│  (CLI first) │     │  (scripts + agent logic)  │     │                │     │  (Trello first)          │
└─────────────┘     └──────────┬───────────────┘     └───────┬────────┘     └────────────┬─────────────┘
                               │                             │                           │
                               │                             │                           │
                    ┌──────────▼───────────┐                 │                           │
                    │  Search Algorithm    │                 │                           │
                    │  (not AI)            │                 │                           │
                    └──────────┬───────────┘                 │                           │
                               │                             │                           │
                    ┌──────────▼───────────┐                 │                           │
                    │  Indexer             │<────────────────┘                           │
                    │  (main DB for search)│                                             │
                    └──────────┬───────────┘                                             │
                               │                                                         │
                    ┌──────────▼───────────┐                                             │
                    │  Files and Data      │<────────────────────────────────────────────┘
                    │  (your dataset)      │
                    └──────────────────────┘
```

**Data flows:**
- The **Interface** sends user requests to the **Orchestrator**.
- The **Orchestrator** decides what to do: it may query the **Search Algorithm** to find relevant data, call **Models/Agents** for reasoning, or trigger **External Integrations**.
- The **Search Algorithm** uses the **Indexer** (database) to find relevant content from **Files and Data**.
- **Models/Agents** can read from and write to both the **Indexer** and **Files and Data**.
- **External Integrations** (like Trello) can also read from and write to **Files and Data**.

---

## Component Details

### 1. Interface (CLI first)

**What it does:** This is how you talk to Harle — the "front door" of the system. You type a request, and it sends that request to the Orchestrator running on a remote server. Later it shows you the result.

**Important architectural note:** The CLI is a **thin client**. It does not run any AI logic, load any models, or process data. All it does is send your request over the network to the Orchestrator (via an HTTP/REST API) and display the response. This means the CLI has no dependency on AI/ML libraries — it only needs to make HTTP calls and render text.

The first interface is a command-line tool (CLI) — a program you run in your terminal. Think of it like a chat window, but in text mode.

**Why CLI first:**
- **Simplest to build.** A CLI has no buttons, no styling, no browser. You focus on the logic, not the look.
- **Developer-friendly.** You are already using a terminal (e.g. in Cursor). A CLI fits naturally into that workflow.
- **Easy to extend later.** Once the CLI works, you can add a web chat UI, a Telegram bot, or a Slack integration on top — they all just send the same request to the Orchestrator's API.

**Technology: Go with [Cobra](https://cobra.dev/)**

Since the CLI is a thin HTTP client, the language choice is **independent** from the server side. The server (Orchestrator) is written in Python because of the AI/ML ecosystem, but the CLI has no AI dependencies — it only sends JSON over HTTP and renders the response.

**Why Go:**
- **Single binary.** `go build` produces one executable file with zero dependencies. You copy it to any machine (Linux, macOS, Windows, even a phone via Termux) and it works. No runtime, no `pip install`, no virtual environments.
- **Fast startup.** Go binaries start in ~10ms. For a CLI you run many times a day, this feels instant — compared to ~200–500ms for a Python CLI that has to load an interpreter.
- **Industry standard for CLI tools.** Docker, Kubernetes (`kubectl`), GitHub CLI (`gh`), Terraform, and Hugo are all written in Go. The ecosystem for building CLI tools in Go is mature and well-documented.
- **Easy cross-compilation.** One command builds the binary for any OS/architecture: `GOOS=linux GOARCH=arm64 go build`. This is useful for deploying to different machines.
- **Cobra library.** Cobra is the de facto standard for Go CLI applications. It provides subcommands, flags, auto-generated help, shell completions, and argument validation out of the box.

**Why not Python for the CLI:**
The server is Python, but that does not mean the CLI should be too. The CLI talks to the server via a simple HTTP API (JSON in, JSON out) — there is no shared business logic, no imported modules. The only cost of using a different language is maintaining a small API contract (a few JSON request/response schemas), which is trivial. The benefits (single binary, fast startup, easy distribution) far outweigh this.

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

### 6. External Integrations (Trello + Web Search from day one)

**What it does:** External Integrations are connectors that let Harle interact with third-party services and the outside world. They allow agents to read from and write to tools you already use — like Trello boards — and to search the internet for fresh information.

**Technology: Python wrapper functions exposed via [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) standard**

**What is MCP?**  
MCP (Model Context Protocol) is a standard way to expose tools to AI models. Instead of each tool having a custom integration, MCP defines a common format: "here is a tool, here is what it does, here are its inputs and outputs." Any orchestrator that speaks MCP can use any MCP-compatible tool.

**Why MCP:**
- **Portability.** If you ever switch orchestrators (e.g. from OpenAI Agents SDK to LangGraph), your tool integrations still work.
- **Standardized.** One format for all tools, instead of writing custom glue code for each.
- **Growing ecosystem.** More and more tools are publishing MCP connectors.

#### 6a. Trello

**Why Trello from day one:**
- **Immediate value.** You already use Trello for task management. Connecting it means Harle can read your tasks, suggest priorities, detect stalled work, and propose updates.
- **Read-write patterns are clear.** Trello has a simple API: lists, cards, labels, due dates. This makes it a safe first integration.
- **Low risk.** Even if something goes wrong, a misplaced Trello card is easy to fix.

**Integration approach (safety first):**
1. Start **read-only**: agents can fetch Trello cards but cannot modify them.
2. Later, enable **propose mode**: agents suggest changes (e.g. "move this card to Done") and wait for your approval.
3. Finally, enable **auto mode** for low-risk actions (e.g. adding a due date) while keeping approval gates for destructive actions (e.g. archiving a card).

#### 6b. Web Search

**Why Web Search from day one:**

Your personal dataset contains what you already know. But many of Harle's planned tasks — research, market analysis, travel planning, news preparation, finding concert tickets — require **information you don't have yet**. Without web search, Harle is limited to your existing notes and whatever the LLM memorized during training (which is outdated and often wrong for specific facts). Web search transforms Harle from a "smart note assistant" into an actual research tool.

**Technology: Commercial search API — [Tavily](https://tavily.com/) or [Bing Web Search API](https://www.microsoft.com/en-us/bing/apis/bing-web-search-api)**

**What is a search API?**  
A search API is a service that lets your code perform web searches programmatically. You send a query ("best flights to Tokyo March 2026"), the API returns structured results (titles, URLs, snippets) — just like Google, but for machines instead of humans.

**Why a commercial search API to start:**
- **Fastest to integrate.** One API key, a few lines of Python, and web search is working. No infrastructure to deploy or maintain.
- **High-quality results.** Services like Tavily and Bing have mature ranking algorithms and broad web coverage. You get reliable, relevant results immediately.
- **AI-optimized (Tavily).** Tavily is built specifically for AI agents — it returns clean, extracted content rather than raw HTML, which reduces the work your Orchestrator needs to do before passing results to the model.
- **Low cost at personal scale.** Tavily offers a free tier (1,000 searches/month) and a paid tier at ~$0.004 per search. Bing API offers 1,000 free calls/month, then ~$0.005 per call. For personal use, this is a few dollars per month at most.
- **Focus on what matters.** At this stage, the goal is to get the agent loop working end-to-end. Spending time setting up self-hosted search infrastructure is a distraction from building the core product.

**Tavily vs. Bing API:**

| Criteria | Tavily | Bing Web Search API |
|---|---|---|
| **Designed for** | AI agents specifically | General-purpose search |
| **Response format** | Clean extracted content, ready for LLMs | Raw snippets, may need post-processing |
| **Free tier** | 1,000 searches/month | 1,000 calls/month |
| **Ease of integration** | Very simple Python SDK | REST API, straightforward |
| **Result quality** | Excellent for research tasks | Excellent, broader web coverage |

Either works well. Tavily is slightly easier for AI agent use cases; Bing has broader coverage. The MCP wrapper abstracts this choice — switching between them later is a one-line change.

**How it fits the architecture:**  
The Orchestrator calls the search API through an MCP-compatible wrapper, just like Trello. The wrapper sends a search query, receives results (titles, URLs, snippets/content), and the Orchestrator adds the most relevant pieces to the model's context.

**Web search flow:**
```
Agent needs external information
         │
         ▼
Orchestrator calls Web Search tool
         │
         ▼
Search API returns results (title, URL, content)
         │
         ▼
Orchestrator selects the top 3–5 most relevant results
         │
         ▼
Content is trimmed and added to the model's context
alongside your dataset search results
```

**Why not just use the LLM's built-in knowledge?**  
LLMs are trained on data from months or years ago. They do not know today's prices, recent news, current flight schedules, or the latest version of a library. Web search gives the agent access to **live, current information** — which is essential for research, travel planning, news, and event tracking.

**Future improvement: migrate to [SearXNG](https://docs.searxng.org/) (self-hosted meta search engine).**  
SearXNG is a free, open-source meta search engine that you host yourself. It queries multiple search engines (Google, Bing, DuckDuckGo, etc.) on your behalf and aggregates results. Benefits over commercial APIs: zero cost per query (unlimited searches), full privacy (searches stay on your server), and no vendor dependency. The migration is straightforward — SearXNG returns the same kind of data (titles, URLs, snippets), so only the MCP wrapper internals change. This is worth doing once Harle is stable and search volume grows beyond the free API tiers.

#### Planned integrations (after Trello and Web Search)

| Service | Use case | Priority |
|---|---|---|
| **GitHub** | Read PRs, summarize changes, propose review comments | High |
| **Notion** | Read/write research documents, store reports | High |
| **Calendar** | Schedule-aware task planning | Medium |
| **Telegram** | Mobile access to Harle via chat | Medium |

---

### 7. Files and Data (your dataset)

**What it does:** This is your personal knowledge base — the collection of Markdown files, notes, rules, prompts, and documents that Harle operates over. It is the "ground truth" that agents refer to when making decisions.

**Technology: Plain Markdown files in an [Obsidian](https://obsidian.md/)-style vault, synced via Git or [Syncthing](https://syncthing.net/)**

**What is an Obsidian-style vault?**  
It is simply a folder of Markdown files organized in directories. Obsidian is a popular note-taking app that uses this format, but you do not need Obsidian — any text editor works. The key idea is that your data is **plain files**, not locked inside a proprietary database.

**Why Markdown files:**
- **Human-readable.** You can open, read, and edit any file with any text editor. No special tools required.
- **Version-controlled.** Put the vault in a Git repository and you get full history: who changed what, when, and why.
- **Portable.** If Harle stops working tomorrow, your data is still usable. It is just text files.
- **Searchable.** Both traditional search (grep, Whoosh) and AI-based search work well on Markdown.

**Why Git for syncing:**
- **You already use it.** As a developer, Git is already part of your workflow.
- **Conflict resolution.** If you edit a file on one computer while Harle edits it on another, Git can show you the conflict and let you resolve it.
- **History.** Every change is tracked, so you can always go back.

**Alternative: Syncthing** for real-time sync without commits. Useful if you want automatic, seamless sync between two computers without thinking about Git operations.

**Vault structure (recommended):**

```
harle-vault/
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
| **CLI (Interface)** | Go + Cobra | Single binary, fast startup, no runtime needed |
| **Orchestrator** | OpenAI Agents SDK | Full control, clean logs, MCP support |
| **Search** | Whoosh | Pure Python, no external services, fast |
| **Database** | PostgreSQL + pgvector | One DB for everything, industry standard |
| **Models** | OpenAI API (now), self-hosted (later) | Best quality today, clean migration path |
| **Integrations** | MCP-compatible Python wrappers | Portable, standardized |
| **Web Search** | Tavily or Bing API (now), SearXNG (later) | Fast to integrate, AI-optimized, low cost at personal scale |
| **Data storage** | Markdown files in Git repo | Human-readable, version-controlled |
| **Deployment** | Docker Compose | One command to start everything |
| **Networking** | Tailscale | Private, secure, zero-config |
| **Sync** | Git or Syncthing | Familiar, reliable, conflict-aware |

---

## Security Approach

Harle follows a "secure enough, not paranoid" philosophy:

1. **Separate contexts.** Work and personal data live in separate directories (or database schemas) with different access rules.
2. **Read-first, write-later.** All integrations start as read-only. Write access is enabled explicitly, per tool, with approval gates.
3. **No secrets in the vault.** API keys and tokens live in environment variables or a secrets manager (e.g. Docker secrets), never in your Markdown files.
4. **Private network only.** Harle is only accessible over Tailscale — no public ports, no public URLs.
5. **Audit log.** Every agent run is logged: what was asked, what was decided, what tools were called, what was returned. This is how you build trust.
6. **Propose-only mode.** Agents draft results and suggest actions. You approve before anything is executed — especially for work-related tasks.

---

## How It All Fits Together (Example Flow)

Here is a concrete example of what happens when you ask Harle: *"Find all stalled tasks in Trello and suggest how to reformulate them."*

```
1. You type the request in the CLI (Interface)
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
4. Orchestrator calls Trello integration (External Integration)
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
7. Response travels back over the network to your CLI
   → CLI displays the suggestions to you
   → You review, approve, or modify
```

---

## What Comes Next

This architecture is designed to grow. The first version focuses on:

1. **CLI interface** — talk to Harle from the terminal
2. **One agent role** (Secretary) — the most immediately useful
3. **Trello integration** — read-only at first
4. **Web Search** — enables research and live information from the start
5. **Markdown dataset** — your knowledge base
6. **PostgreSQL** — logging and search index
7. **OpenAI models** — for reasoning

Once this loop works reliably, the next steps are:
- Add Researcher and Specialist roles
- Enable write integrations (with approval)
- Add semantic search (pgvector)
- Deploy to a VPS for always-on access
- Add Telegram or web chat interface
