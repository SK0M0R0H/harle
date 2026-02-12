# Harle Orchestrator — Architecture & Functionality

> The Orchestrator is the central component of Harle. It receives every request, decides what to do, coordinates all other components, and returns the result. Everything flows through it.

This document describes the Orchestrator's internal architecture, its responsibilities, how it processes a request from start to finish, and the technology choices behind each part. It is written for someone who may not have deep backend experience.

For the overall system architecture, see [architecture.md](./architecture.md).

---

## Where the Orchestrator Sits

```
                        ┌──────────────────────────────────────────────┐
                        │              ORCHESTRATOR                    │
CLI ──HTTP──>           │                                              │
                        │  ┌──────────┐   ┌──────────┐   ┌─────────┐  │
                        │  │ HTTP API │──>│ Router   │──>│ Agent   │  │
                        │  │ (FastAPI)│   │          │   │ Runner  │  │──── LLM API (OpenAI)
                        │  └──────────┘   └────┬─────┘   └────┬────┘  │
                        │                      │              │       │
                        │                 ┌────▼─────┐   ┌────▼────┐  │
                        │                 │ Clarifier│   │  Tool   │  │──── External Integrations
                        │                 │          │   │ Manager │  │     (Trello, Web Search)
                        │                 └──────────┘   └────┬────┘  │
                        │                                     │       │
                        │  ┌──────────┐   ┌──────────┐   ┌────▼────┐  │
                        │  │ Run      │   │ Context  │   │ Search  │  │
                        │  │ Logger   │   │ Assembler│   │ Client  │  │──── Dataset (files)
                        │  └────┬─────┘   └────┬─────┘   └─────────┘  │
                        │       │              │                      │
                        │       └──────┬───────┘                      │
                        │              ▼                               │
                        │         PostgreSQL                           │
                        └──────────────────────────────────────────────┘
```

The Orchestrator is a **single Python service** running on the server. It contains several internal modules that work together to process every request. From the outside, it looks like one HTTP endpoint. Inside, it is a pipeline of clearly separated steps.

---

## Internal Modules

The Orchestrator consists of seven internal modules. Each has one job. They are described below in the order a request flows through them.

### 1. HTTP API (the entry point)

**What it does:** Accepts requests from the CLI (or any future interface) and returns responses. This is the only part of the Orchestrator that is visible from the outside.

**Technology: [FastAPI](https://fastapi.tiangolo.com/)**

**What is FastAPI?**
FastAPI is a Python web framework for building APIs. When you hear "API," think of it as a door with a specific format: you knock in a certain way (send a JSON request), and you get a structured response back. FastAPI handles all the low-level details — parsing JSON, validating inputs, returning errors with proper HTTP codes.

**Why FastAPI:**
- **Async by default.** FastAPI uses Python's `async/await`, which means it can handle multiple requests at the same time without blocking. This matters when a request is waiting for an LLM response (which can take seconds) — other requests can still be processed.
- **Automatic validation.** You define what a request should look like (using Pydantic models), and FastAPI rejects malformed requests before your code even runs. This prevents bugs and makes the API self-documenting.
- **Auto-generated docs.** FastAPI produces interactive API documentation (Swagger UI) at `/docs` automatically. You can test endpoints from the browser without writing a single line of client code.
- **Industry standard for Python APIs.** FastAPI is the most popular modern Python web framework. It is used by Microsoft, Netflix, Uber, and many others.
- **Lightweight.** Unlike Django (which is a full web framework with admin panels, template rendering, ORM, etc.), FastAPI does one thing well — serve APIs. Since the Orchestrator is an API-only service with no web pages, FastAPI is the right tool.

**Why not Flask?**
Flask is simpler but synchronous by default. Since every Orchestrator request involves waiting for LLM calls (1–10 seconds each), a synchronous server would block on every request. FastAPI's async support is essential for responsiveness.

**API endpoints (first version):**

| Endpoint | Method | What it does |
|---|---|---|
| `POST /run` | POST | Submit a new task. Returns the result (or a run ID for long tasks). |
| `POST /chat` | POST | Send a message in an ongoing conversation. Supports multi-turn dialogue. |
| `GET /run/{id}` | GET | Check the status and result of a previously submitted task. |
| `GET /health` | GET | Simple health check — returns "ok" if the service is running. |

**Request format (example):**
```json
{
  "message": "Find all stalled tasks in Trello and suggest reformulations",
  "context": "work",
  "conversation_id": null
}
```

- `message` — what the user wants.
- `context` — "work" or "personal" (determines which dataset scope and policies apply).
- `conversation_id` — `null` for a new task, or an ID to continue an existing conversation.

**Response format (example):**
```json
{
  "run_id": "run_2026-02-12_001",
  "status": "completed",
  "agent": "secretary",
  "result": "Found 7 stalled tasks. Here are suggested reformulations:\n\n1. ...",
  "tools_used": ["trello_read"],
  "clarification_needed": false
}
```

**Streaming support:**
For long-running tasks (like research reports), the API supports **Server-Sent Events (SSE)** — a standard way to stream partial results to the client as they are generated. The CLI shows text appearing in real-time, similar to how ChatGPT streams responses word by word. This is important for user experience: without streaming, you stare at a blank screen for 30 seconds until the full response arrives.

---

### 2. Router (which agent handles this?)

**What it does:** The Router examines the incoming request and decides which **agent role** should handle it. This is the first decision point in the pipeline.

**How routing works:**

The Router does not use AI for this decision. It uses a combination of simple, deterministic rules — because routing must be fast, predictable, and cheap. AI is reserved for the actual thinking work inside the agent.

**Routing strategy (layered):**

```
Step 1: Explicit override
  → User said "as researcher: ..." or used a flag like --role=researcher
  → Use that role directly. Skip to agent execution.

Step 2: Context-based rules
  → Request mentions "Trello", "tasks", "schedule" → Secretary
  → Request mentions "research", "report", "analyze market" → Researcher
  → Request mentions "dataset", "prompts", "agent logs" → Specialist

Step 3: Keyword matching against workflow templates
  → Search the vault's workflows/ directory for matching templates
  → If a template matches, use the role it specifies

Step 4: Fallback to LLM classification
  → If steps 1–3 produce no clear match, ask the LLM:
    "Given this request: [...], which role should handle it?
     Options: researcher, secretary, specialist"
  → This is a cheap, fast call (a single sentence response)
```

**Why this layered approach:**
- **Steps 1–3 are free and instant.** No API call, no latency, no cost.
- **Step 4 is a safety net.** It only triggers for ambiguous requests — maybe 10–20% of the time.
- **Predictable.** You can look at the rules and know exactly why a request was routed to a specific agent. No black box.

**Agent roles (first version):**

| Role | Purpose | When it activates |
|---|---|---|
| **Secretary** | Task management, summaries, daily workflow, Trello interaction | Requests about tasks, schedules, Trello, summaries, organization |
| **Researcher** | Information gathering, report writing, analysis | Requests about research, reports, market analysis, technical comparison |
| **Specialist** | System self-improvement, dataset maintenance, log analysis | Requests about Harle itself, dataset quality, agent performance |

Each role is defined by a **prompt file** in the dataset vault (e.g. `prompts/secretary.md`). The prompt file contains:
- The agent's identity and purpose.
- Rules and constraints (what it can and cannot do).
- The tools it is allowed to use.
- Output format preferences.
- Example interactions.

This means you can customize any agent's behavior by editing a Markdown file — no code changes required.

---

### 3. Clarifier (is the request clear enough?)

**What it does:** Before an agent starts working, the Clarifier checks whether the request is specific enough to produce a good result. If it is not, it asks the user 1–3 targeted questions.

**Why this matters:**

The project requirements explicitly state that Harle must "handle vague goals." Humans are bad at writing precise instructions — we say "do something about the Japan trip tasks" when we mean "find all Trello cards tagged 'Japan', check which ones have no due date, and propose a timeline." A good assistant does not guess — it asks.

**How the Clarifier works:**

```
Input: user's request + agent role

Step 1: Check if the request matches a known workflow template
  → If yes, the template already defines the steps. No clarification needed.

Step 2: Use the LLM to evaluate ambiguity
  → Prompt: "You are about to handle this request as a [role].
     Is this request clear enough to act on?
     If not, what 1–3 questions would you ask?"
  → This is a cheap, fast call — the LLM responds with either
    "clear, proceed" or a short list of questions.

Step 3: If questions are needed
  → Return them to the user via the API
  → The CLI displays them and collects answers
  → Answers are appended to the request, and the pipeline continues

Step 4: Store the clarified request
  → Save the final, clarified version in the run log
  → Over time, this builds a dataset of "vague request → clarified request"
    pairs that can improve future routing and templates
```

**Example:**

User says: *"Do something about the Japan trip"*

Clarifier responds:
1. "Which Trello board contains the Japan trip tasks?"
2. "What should I focus on: missing due dates, stalled tasks, or budget items?"
3. "Should I update the tasks directly or prepare a summary for your review?"

User answers, and now the agent has a precise task.

**Important design decision:** Clarification is a **separate step** from agent execution. The agent does not start working until the request is clear. This prevents wasted LLM calls on misunderstood tasks.

**When clarification is skipped:**
- The request explicitly matches a workflow template.
- The user used the `--no-clarify` flag (for scripted/automated use).
- The request is a follow-up in an existing conversation (context is already established).

---

### 4. Context Assembler (gather the right information)

**What it does:** Once the request is clear and routed, the Context Assembler gathers all the information the agent needs before calling the LLM. This is the **most critical module** in the Orchestrator — it determines the quality of every response.

**Why this exists (the context window problem):**

As described in [architecture.md](./architecture.md), language models have a hard limit on how much text they can process (the "context window"). Your dataset can be far larger than this limit. The Context Assembler's job is to select the **most relevant pieces** from your dataset, prior runs, and external sources — and pack them into a focused context that fits the model's window and maximizes response quality.

**What the Context Assembler collects:**

```
┌─────────────────────────────────────────────────────────┐
│                    CONTEXT PACKAGE                       │
│                                                         │
│  1. Agent prompt (from vault: prompts/secretary.md)     │
│  2. Relevant policies (from vault: policies/*.md)       │
│  3. Matching workflow template (if any)                 │
│  4. Dataset search results (from Search Algorithm)      │
│  5. Prior run history (similar past requests)           │
│  6. User preferences and decisions (from memories DB)   │
│  7. External data (Trello cards, web search results)    │
│  8. Conversation history (if multi-turn chat)           │
│                                                         │
│  Total: must fit within the model's context window      │
│  Budget: ~80% for context, ~20% reserved for response   │
└─────────────────────────────────────────────────────────┘
```

**How it decides what to include (priority system):**

Not everything can fit. The Context Assembler uses a **priority-based budget system**:

| Priority | Content type | Always included? | Typical size |
|---|---|---|---|
| **P0 (mandatory)** | Agent prompt + policies | Yes | ~1–2 pages |
| **P1 (critical)** | Direct search results from dataset | Yes | ~3–5 pages |
| **P2 (important)** | External data (Trello cards, web results) | If available | ~2–4 pages |
| **P3 (helpful)** | Prior run history, user preferences | If budget allows | ~1–2 pages |
| **P4 (background)** | Conversation history, extra examples | Trimmed to fit | Variable |

The assembler starts with P0, adds P1, and keeps adding lower priorities until the token budget is reached. If something does not fit, lower-priority items are trimmed or dropped.

**How search results are gathered:**

The Context Assembler calls the **Search Client** (see below) to query both:
- **Full-text search (Whoosh):** finds documents matching keywords from the request.
- **Semantic search (pgvector, future):** finds documents matching the meaning of the request.

Results are ranked by relevance and deduplicated. The top results become part of the context package.

**Token counting:**

The assembler needs to know how much text fits in the model's context window. It uses a **tokenizer** (a tool that counts tokens — the units LLMs use to measure text length) to track the budget precisely. The [tiktoken](https://github.com/openai/tiktoken) library (from OpenAI) does this in microseconds.

**Why this is not just "send everything":**

Sending too much context is as bad as sending too little:
- **Too little:** the model does not have enough information and makes things up.
- **Too much:** the model gets "distracted" by irrelevant content and gives diluted, unfocused answers. Research shows that models perform worse when buried in irrelevant context ("lost in the middle" problem).
- **Just right:** the model gets a focused, relevant package and produces a high-quality, specific answer.

The Context Assembler is what makes the difference between a generic chatbot and a personalized assistant that knows your rules, preferences, and history.

---

### 5. Agent Runner (do the actual work)

**What it does:** The Agent Runner takes the assembled context and the clarified request, and executes the agent — meaning it calls the LLM, potentially multiple times, with tool use in between, until the task is complete.

**Technology: [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)**

**What the Agents SDK does under the hood:**

The SDK implements an **agentic loop** — a pattern where the LLM can decide to call tools, inspect the results, and then decide what to do next. This is fundamentally different from a simple chat completion where you send one message and get one response.

**The agentic loop:**

```
                    ┌─────────────────────┐
                    │  Start: send prompt │
                    │  + context to LLM   │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  LLM responds       │
                    │  with either:       │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
   ┌──────────▼───┐  ┌────────▼─────┐  ┌───────▼────────┐
   │  Final text  │  │  Tool call   │  │  Handoff to    │
   │  response    │  │  request     │  │  another agent │
   │              │  │              │  │                │
   │  → Done!     │  │  → Execute   │  │  → Switch role │
   │  Return to   │  │  the tool,   │  │  and restart   │
   │  user        │  │  feed result │  │  the loop      │
   └──────────────┘  │  back to LLM │  └────────────────┘
                     │  → Loop back │
                     └──────────────┘
```

**Example of a multi-step loop:**

Request: *"Find stalled Trello tasks and suggest reformulations"*

```
Loop iteration 1:
  LLM sees: prompt + context + request
  LLM decides: "I need to read Trello cards first"
  LLM calls: tool:trello_list_cards(board="Work")
  Tool returns: [list of 23 cards with dates]

Loop iteration 2:
  LLM sees: prompt + context + request + Trello data
  LLM decides: "I can now identify stalled tasks and write suggestions"
  LLM returns: final text response with 7 stalled tasks and reformulations

→ Done. Result returned to user.
```

**Guardrails built into the Agent Runner:**

The Agent Runner enforces safety rules that the LLM cannot override:

| Guardrail | What it prevents |
|---|---|
| **Tool allowlist** | Agent can only call tools listed in its prompt file. A Researcher cannot write to Trello. |
| **Approval gate** | Write actions (create card, update page) pause and ask for user confirmation before executing. |
| **Max iterations** | The agentic loop is limited (e.g. 10 iterations). If the agent loops too many times, the run is stopped and the user is notified. |
| **Timeout** | Total execution time is capped (e.g. 5 minutes). Long-running tasks are stopped gracefully. |
| **Token budget** | Total tokens used per run are tracked. If the cost exceeds a threshold, the run is paused. |
| **Output validation** | The final output is checked for basic quality: not empty, not a repetition of the input, no tool-calling artifacts leaked into the response. |

**Handoffs (multi-agent collaboration):**

Sometimes a task needs more than one agent. The Agents SDK supports **handoffs** — one agent can pass the task to another mid-execution.

Example: a Secretary agent receives *"Research privacy solutions and create a Trello card with the findings."*
1. Secretary realizes this needs research → hands off to Researcher.
2. Researcher searches the web and dataset, produces a summary → hands back to Secretary.
3. Secretary creates a Trello card draft with the summary → asks for approval.

Handoffs are logged. Each agent in the chain only has access to its own tools — the Researcher cannot create Trello cards, even during a handoff.

---

### 6. Tool Manager (connect to the outside world)

**What it does:** The Tool Manager is the Orchestrator's gateway to external services. Every time an agent needs to read Trello cards, search the web, or read/write files in the dataset, the call goes through the Tool Manager.

**Why a separate module (instead of letting agents call APIs directly):**
- **Centralized control.** All external calls go through one place. You can add logging, rate limiting, and approval gates without changing each tool.
- **Abstraction.** Agents do not know how Trello's API works. They just call `trello_list_cards(board="Work")`. The Tool Manager handles authentication, retries, error formatting, and response parsing.
- **Swappable.** If you switch from the Trello API to a Trello MCP server, only the Tool Manager changes. Agents and the Orchestrator are untouched.

**How tools are defined:**

Each tool is a Python function decorated with metadata that describes it to the LLM:

```python
@tool(
    name="trello_list_cards",
    description="List all cards on a Trello board, including their status, labels, and due dates.",
    permission="read",        # read | write | delete
    requires_approval=False,  # read actions don't need approval
)
def trello_list_cards(board: str) -> list[dict]:
    """Calls Trello API and returns cards."""
    ...
```

The LLM sees the `name` and `description` and decides when to call it. The `permission` and `requires_approval` fields are enforced by the Tool Manager, not the LLM — so they cannot be bypassed.

**Tool registry (first version):**

| Tool | Category | Permission | Approval needed? |
|---|---|---|---|
| `trello_list_boards` | Trello | read | No |
| `trello_list_cards` | Trello | read | No |
| `trello_get_card` | Trello | read | No |
| `trello_create_card` | Trello | write | Yes |
| `trello_update_card` | Trello | write | Yes |
| `trello_move_card` | Trello | write | Yes |
| `web_search` | Web Search | read | No |
| `web_fetch_page` | Web Search | read | No |
| `dataset_search` | Dataset | read | No |
| `dataset_read_file` | Dataset | read | No |
| `dataset_write_file` | Dataset | write | Yes (work context) |

**Approval flow for write actions:**

```
Agent decides: "I want to create a Trello card"
         │
         ▼
Tool Manager checks: requires_approval = true
         │
         ▼
Run is paused. Pending action sent to user:
  "Agent wants to create a card:
   Board: Work
   List: To Do
   Title: Research privacy solutions
   Description: [...]
   
   Approve? [y/n]"
         │
    ┌────┴────┐
    │         │
  [yes]     [no]
    │         │
    ▼         ▼
  Execute   Skip action,
  the tool  agent continues
             without it
```

**MCP compatibility:**

Tools are exposed via MCP (Model Context Protocol) standard. This means:
- If you find an existing MCP server for a service (e.g. a community-built Notion MCP server), you can plug it in directly.
- If you later switch orchestrators, your tools still work.
- Other agents or systems can reuse your tools via the same MCP interface.

---

### 7. Run Logger (record everything)

**What it does:** The Run Logger records every detail of every Orchestrator execution. This is the audit trail that lets you understand what happened, debug problems, and build trust in the system over time.

**Why logging matters more than you think:**

Without logs, an AI agent is a black box. You get a result, but you do not know:
- Why the agent chose a certain approach.
- What data it used to make its decision.
- Which tools it called and what they returned.
- Whether the result is based on your data or the model's general knowledge.

The Run Logger answers all of these questions for every single run.

**What is logged:**

```json
{
  "run_id": "run_2026-02-12_001",
  "timestamp": "2026-02-12T14:23:01Z",
  "user_request": "Find stalled tasks in Trello",
  "context_scope": "work",
  "clarification": {
    "needed": false,
    "questions": [],
    "answers": []
  },
  "routing": {
    "agent": "secretary",
    "method": "keyword_match",
    "confidence": "high"
  },
  "context_assembled": {
    "prompt_file": "prompts/secretary.md",
    "policies_loaded": ["tools-allowlist.md"],
    "dataset_search_results": ["workflows/task-triage.md"],
    "prior_runs_referenced": 0,
    "total_tokens_in_context": 3420
  },
  "execution": {
    "model": "gpt-4o-mini",
    "iterations": 2,
    "tool_calls": [
      {
        "tool": "trello_list_cards",
        "input": {"board": "Work"},
        "output_summary": "23 cards returned",
        "duration_ms": 340
      }
    ],
    "total_tokens_used": 5890,
    "total_duration_ms": 4200,
    "estimated_cost_usd": 0.003
  },
  "result": {
    "type": "text",
    "length_chars": 1240,
    "stored_as": "logs/2026-02/run_001_result.md"
  },
  "approval_actions": []
}
```

**Where logs are stored:**
- **PostgreSQL** (`runs` table) — structured log data for querying ("show me all runs from last week that used Trello tools").
- **Dataset vault** (`logs/` directory) — human-readable result files in Markdown, for your own review.

**What logs enable over time:**
- **Debugging.** If a result is wrong, you can trace exactly what happened: which context was used, which tools were called, what the model saw.
- **Cost tracking.** You know exactly how many tokens and API calls each task uses. You can spot expensive patterns and optimize.
- **Quality improvement.** By reviewing past runs, you can improve prompts, add workflow templates, and refine routing rules.
- **The Specialist agent.** The Specialist agent role uses these logs to analyze system performance and suggest improvements. Without logs, the Specialist has nothing to work with.

---

## Request Lifecycle (complete flow)

Here is the full lifecycle of a request, from the moment you hit Enter to the moment the CLI shows the result:

```
 YOU (CLI)                        ORCHESTRATOR (server)
    │
    │  POST /run
    │  {"message": "...", "context": "work"}
    │──────────────────────────>│
    │                          │
    │                    1. HTTP API
    │                       Validates request, extracts fields
    │                          │
    │                    2. Router
    │                       Determines agent role (secretary/researcher/specialist)
    │                       Method: keyword rules → workflow match → LLM fallback
    │                          │
    │                    3. Clarifier
    │                       Checks if request is specific enough
    │                       If not: returns questions to user
    │  <──── questions ────────│  (optional round-trip)
    │──── answers ────────────>│
    │                          │
    │                    4. Context Assembler
    │                       Queries Search Algorithm (Whoosh) for relevant files
    │                       Loads agent prompt, policies, workflow templates
    │                       Retrieves prior run history and user preferences
    │                       Fetches external data if needed (Trello cards, web results)
    │                       Packs everything into a token-budgeted context package
    │                          │
    │                    5. Agent Runner
    │                       Sends context + request to LLM
    │                       LLM may call tools → Tool Manager → loop back
    │                       Enforces guardrails (max iterations, timeout, allowlist)
    │                       On write actions: pauses for user approval
    │  <── approval request ───│  (optional round-trip)
    │──── approve/deny ───────>│
    │                       Collects final response
    │                          │
    │                    6. Run Logger
    │                       Records everything: request, routing, context, tools,
    │                       tokens, cost, result
    │                       Saves to PostgreSQL + vault logs/
    │                          │
    │                    7. HTTP API
    │                       Formats and returns response
    │  <───── result ──────────│
    │
 YOU see the result
```

---

## Conversation Mode (multi-turn chat)

Not every interaction is a one-shot task. Sometimes you want to have a conversation — ask follow-up questions, refine the result, or explore a topic step by step, similar to ChatGPT.

**How it works:**

1. The first message creates a **conversation** with a unique ID.
2. Subsequent messages include this conversation ID.
3. The Orchestrator loads the conversation history from PostgreSQL and includes it in the context.
4. The Router and Clarifier can use conversation history to make better decisions (e.g. if you already said "let's work on the Japan trip," the Clarifier does not need to ask which project you mean).

**What is stored per conversation:**

| Field | Purpose |
|---|---|
| `conversation_id` | Unique identifier |
| `messages` | Full history of user messages and agent responses |
| `agent_role` | Which agent is active (can change mid-conversation via handoff) |
| `context_scope` | "work" or "personal" |
| `active_tools` | Which tools have been used or approved |
| `created_at` / `updated_at` | Timestamps |

**Context window management in conversations:**

Long conversations accumulate a lot of text. The Context Assembler handles this by:
- **Keeping recent messages in full** (last 5–10 turns).
- **Summarizing older messages** — using the LLM to compress earlier turns into a brief summary. This preserves the key decisions and context without consuming the entire token budget.
- **Always reserving space** for dataset search results and the agent prompt. Conversation history never crowds out the core context.

---

## Configuration

The Orchestrator is configured through a combination of:

| Configuration source | What it controls | Example |
|---|---|---|
| **Environment variables** | Secrets, API keys, database URL | `OPENAI_API_KEY`, `DATABASE_URL`, `TRELLO_API_KEY` |
| **Config file** (`config.yaml`) | Service settings, defaults, limits | Max iterations, timeout, token budget, default model |
| **Dataset vault** (Markdown files) | Agent prompts, policies, workflows | `prompts/secretary.md`, `policies/tools-allowlist.md` |

**Example `config.yaml`:**

```yaml
server:
  host: "0.0.0.0"
  port: 8000

models:
  default: "gpt-4o-mini"          # For routine tasks (cheap, fast)
  complex: "gpt-4o"               # For research, analysis (better quality)
  classifier: "gpt-4o-mini"       # For routing fallback and clarification

limits:
  max_iterations: 10              # Max agentic loop iterations per run
  timeout_seconds: 300            # Max total time per run (5 minutes)
  max_tokens_per_run: 50000       # Cost safety cap
  max_conversation_turns: 50      # Prevent infinite conversations

search:
  max_results: 10                 # Max files returned by dataset search
  max_context_pages: 8            # Max pages of context sent to LLM

approval:
  require_for_write: true         # All write actions need user approval
  auto_approve_read: true         # Read actions proceed automatically
  work_context_strict: true       # Extra caution for work-related actions
```

This file lives in the repository, not in the dataset vault (it is a service configuration, not user knowledge). You can override any value with environment variables for deployment flexibility.

---

## Error Handling

Things will go wrong. The Orchestrator handles errors at each level:

| Error type | What happens | User experience |
|---|---|---|
| **LLM API down** | Retry 3 times with exponential backoff. If still failing, return an error with a clear message. | "OpenAI API is unavailable. Your request has been saved and can be retried." |
| **LLM returns garbage** | Output validation catches it. The run is logged as failed. | "The model produced an unusable response. Please try again or rephrase." |
| **Tool call fails** | Error is passed back to the LLM, which can try a different approach or report the issue. | "Could not read Trello cards (authentication error). Check your API key." |
| **Timeout** | Run is stopped gracefully. Partial results are saved. | "This task took too long. Here is what was completed so far: [...]" |
| **Token budget exceeded** | Run is paused. User is asked whether to continue (costs more). | "This task is using more tokens than expected ($0.15 so far). Continue?" |
| **Search returns nothing** | Agent proceeds with general knowledge only. A warning is included. | Result includes: "Note: no matching documents found in your dataset." |

All errors are logged in the Run Logger with full details for debugging.

---

## Project Structure (Python)

```
harle-server/
├── pyproject.toml              # Dependencies and project metadata
├── Dockerfile                  # Container definition
├── config.yaml                 # Service configuration
│
├── src/
│   └── harle/
│       ├── __init__.py
│       ├── main.py             # FastAPI app entry point
│       │
│       ├── api/                # HTTP API layer
│       │   ├── routes.py       # Endpoint definitions (/run, /chat, etc.)
│       │   └── models.py       # Request/response Pydantic models
│       │
│       ├── router/             # Agent routing logic
│       │   ├── router.py       # Layered routing strategy
│       │   └── rules.py        # Keyword rules and pattern matching
│       │
│       ├── clarifier/          # Ambiguity detection and question generation
│       │   └── clarifier.py
│       │
│       ├── context/            # Context assembly and token budgeting
│       │   ├── assembler.py    # Priority-based context packing
│       │   └── tokenizer.py    # Token counting (tiktoken wrapper)
│       │
│       ├── agents/             # Agent definitions and execution
│       │   ├── runner.py       # Agentic loop using OpenAI Agents SDK
│       │   ├── definitions.py  # Agent role loading from vault
│       │   └── guardrails.py   # Safety checks, limits, validation
│       │
│       ├── tools/              # Tool Manager and tool implementations
│       │   ├── manager.py      # Central tool registry, approval flow
│       │   ├── trello.py       # Trello API wrapper
│       │   ├── web_search.py   # Tavily/Bing wrapper
│       │   └── dataset.py      # Dataset file read/write
│       │
│       ├── search/             # Search client (interface to Whoosh + pgvector)
│       │   └── client.py
│       │
│       ├── logging/            # Run Logger
│       │   └── run_logger.py
│       │
│       └── db/                 # Database access layer
│           ├── connection.py   # PostgreSQL connection management
│           └── models.py       # Database table definitions (SQLAlchemy)
│
└── tests/
    ├── test_router.py
    ├── test_clarifier.py
    ├── test_context.py
    └── test_tools.py
```

**Key dependencies:**

| Package | Purpose |
|---|---|
| `fastapi` + `uvicorn` | HTTP server |
| `openai-agents` | Agent orchestration SDK |
| `openai` | LLM API client |
| `tiktoken` | Token counting |
| `sqlalchemy` + `asyncpg` | PostgreSQL access (async) |
| `whoosh` | Full-text search index |
| `pydantic` | Data validation and serialization |
| `httpx` | HTTP client for external API calls (Trello, web search) |
| `pyyaml` | Config file parsing |

---

## Technology Choices Summary

| Decision | Choice | Key reason |
|---|---|---|
| **Web framework** | FastAPI | Async, auto-validation, auto-docs, lightweight |
| **Agent framework** | OpenAI Agents SDK | Full control, agentic loop, MCP support, clean logging |
| **LLM for tasks** | GPT-4o / GPT-4o-mini | Best quality, easy to swap later via provider wrapper |
| **LLM for routing** | GPT-4o-mini (fallback only) | Cheap, fast, only used when rules are insufficient |
| **Token counting** | tiktoken | Official OpenAI tokenizer, microsecond speed |
| **Database ORM** | SQLAlchemy (async) | Industry standard, supports Postgres natively |
| **HTTP client** | httpx | Async, modern, replaces requests for async code |
| **Config format** | YAML | Human-readable, supports comments, widely used |
| **Search** | Whoosh (now), pgvector (later) | No external service needed, pure Python |
