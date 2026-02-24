---
title: "Multi-Step Reasoning — Design & Incremental Implementation Plan"
tags: [orchestrator, multi-step-reasoning, agentic-loop, tool-use, planning, react, agents]
context: global
last_updated: 2026-02-24
summary: "Describes multi-step reasoning patterns for the orchestrator, how leading AI companies implement them, and a step-by-step plan from simplest to most complex."
---

# Multi-Step Reasoning — Design & Incremental Implementation Plan

> Multi-step reasoning is what turns a chatbot into an agent. Instead of one prompt → one answer, the orchestrator makes multiple LLM calls — planning, acting, observing, reflecting — before delivering a result. This document describes the patterns, how the best companies implement them, and a concrete incremental plan for Harle.

This document covers:
1. Why multi-step reasoning is necessary.
2. How leading AI companies solve this (OpenAI, Anthropic, Google DeepMind, LangChain).
3. The core reasoning patterns and when each applies.
4. Harle-specific design decisions.
5. A step-by-step incremental implementation plan (7 levels, simplest → most complex).

For the current orchestrator architecture, see [orchestrator.md](./orchestrator.md).

---

## The Problem

Today Harle makes **one LLM call per request**. The flow is:

```
User message → Context Assembly → Single LLM call → Response
```

This works for simple questions ("summarize this article") but fails for real agent tasks:

- **"Find stalled Trello tasks and suggest reformulations"** — requires reading Trello first (tool call), then reasoning over the results (second LLM call).
- **"Research privacy solutions for our L2 architecture"** — requires multiple web searches, reading dataset files, synthesizing across sources, possibly revising the search strategy based on initial findings.
- **"Prepare a status report from Trello, email threads, and last week's notes"** — requires parallel data gathering from multiple tools, then a synthesis pass.

The core limitation: **the LLM cannot discover information it needs mid-reasoning**. Everything must be pre-loaded into context before the single call. This forces the Context Assembler to guess what will be relevant — and it often guesses wrong or loads too much.

Multi-step reasoning solves this by letting the LLM **request information as it reasons**, observe what comes back, and decide what to do next.

---

## How Leading Companies Solve This

### OpenAI — Agents SDK Agentic Loop

OpenAI's approach (implemented in the [Agents SDK](https://openai.github.io/openai-agents-python/), v0.9.2 as of February 2026) is the most directly relevant to Harle since it is the chosen agent framework.

**Core loop:**

```
┌─────────────────────────┐
│  Invoke agent with input │
└────────────┬────────────┘
             │
┌────────────▼────────────┐
│  LLM responds with:     │
│  ┌───────────────────┐  │
│  │ A) Tool calls     │──┼──→ Execute tools, append results, loop back
│  │ B) Handoff        │──┼──→ Switch to another agent, loop back
│  │ C) Final output   │──┼──→ Return result, terminate
│  └───────────────────┘  │
└─────────────────────────┘
```

**Key design decisions:**
- The loop is **model-driven** — the LLM decides when to call tools and when to stop. No external planner tells it what to do.
- **`max_turns`** (default: 10) prevents runaway loops. Exceeding it raises `MaxTurnsExceeded`.
- **Handoffs** allow one agent to delegate to a specialist mid-execution (e.g., Secretary → Researcher).
- **Guardrails** run at each turn: input validation, output validation, tool-call schema checking.
- **Tracing** is built-in — every turn, tool call, and decision is logged for debugging.
- **Sessions** provide persistent memory across turns within a run.

**What Harle can adopt directly:** The `Runner` class, `max_turns`, handoff primitives, and the tracing infrastructure. The SDK is already the chosen framework — the task is wiring it into the existing orchestrator.

---

### Anthropic — Think Tool and Advanced Tool Use

Anthropic takes a different architectural approach by giving the model **explicit reasoning space** and **dynamic tool discovery**.

**The "Think" tool (March 2025):** A special tool that does nothing externally — it just gives Claude a scratchpad to reason before acting. This is particularly effective for:
- Long chains of tool calls where the model needs to track what it has already done.
- Policy-heavy environments where the model must check rules before each action.
- Sequential decisions where each step depends on the previous one.

**Advanced Tool Use (November 2025):**
- **Tool Search Tool** — instead of loading all tool definitions into the prompt (which wastes ~190k tokens for large tool sets), the model can *discover* relevant tools on demand. This is critical when the tool set grows beyond 10–20 tools.
- **Programmatic Tool Calling** — the model writes code to orchestrate tool calls (loops, conditionals, parallel execution) instead of making one tool call at a time. Reduces context window usage and enables complex orchestration patterns.

**What Harle can learn:**
1. An explicit "thinking step" before tool calls improves quality for complex tasks — Harle can add this as a system-prompt instruction or a dedicated tool.
2. For large tool sets, dynamic tool discovery prevents context bloat. Not needed at Harle's current scale (~10 tools) but important for the future.
3. Programmatic tool calling (model generates code to orchestrate tools) is a powerful advanced pattern for parallel data gathering.

---

### Google DeepMind — SELF-DISCOVER and Planning

Google DeepMind focuses on **structured reasoning frameworks** that outperform naive chain-of-thought:

**SELF-DISCOVER (February 2024):** The model first selects which reasoning strategies apply to the task (critical thinking, step-by-step analysis, analogical reasoning), then composes them into a task-specific reasoning structure, then follows that structure. This outperforms standard chain-of-thought by up to 30% on complex benchmarks while using 10–40x fewer inference calls than CoT-Self-Consistency.

**Internal vs. External Planning (December 2024):** Two complementary strategies:
- *Internal search:* The LLM generates a tree of possible next steps within its own context, evaluates them, and picks the best.
- *External search:* The LLM guides a Monte Carlo Tree Search (MCTS) algorithm, exploring multiple paths and backtracking when needed.

**Intelligent Delegation (2025):** A framework for multi-agent systems where delegation is not just task-splitting but includes scoped authority, verification, and monitoring. Agents receive specific permissions for their delegated subtask and results are verified before integration.

**What Harle can learn:**
1. For complex planning tasks (research reports, multi-source analysis), a **plan-first** step dramatically improves quality — the LLM outlines what it will do before doing it.
2. Verification of intermediate results prevents error propagation — each tool call result should be sanity-checked before proceeding.
3. Scoped delegation (specific tools and permissions per sub-agent) matches Harle's existing tool-allowlist design.

---

### LangChain/LangGraph — Patterns Taxonomy

LangChain's ecosystem provides the clearest taxonomy of multi-step reasoning patterns:

**Plan-and-Execute:** Separate the planning LLM call from the execution calls. A powerful model creates a plan; a cheaper model executes each step. The plan can be revised after each step based on results. This is cost-effective and produces better results than reactive patterns for multi-step tasks.

**Reflexion:** After each action cycle, the agent explicitly critiques its own output — what went well, what was missed, what should change. Insights are stored in episodic memory for future reference. Reduces repeated mistakes.

**Language Agents Tree Search (LATS):** The agent explores multiple possible action sequences (like a chess player considering several moves ahead), evaluates each, and commits to the best path. High-quality but expensive — suited for critical decisions.

---

## Core Reasoning Patterns

Based on the industry survey, there are five distinct multi-step reasoning patterns, ordered from simplest to most complex. Each builds on the previous one.

### Pattern 1: Tool-Calling Loop (ReAct)

The foundational pattern. The LLM reasons about what it needs, calls a tool, observes the result, and decides what to do next. This is what OpenAI's Agents SDK implements natively.

```
User: "Find stalled Trello tasks"
  │
  ├─ Turn 1: LLM thinks "I need Trello data" → calls trello_list_cards()
  │           Tool returns 23 cards
  │
  ├─ Turn 2: LLM analyzes cards, identifies 7 stalled → produces final answer
  │
  └─ Result: "Found 7 stalled tasks: ..."
```

**When to use:** Any task that requires external data the LLM does not have in context. This is the minimum viable multi-step pattern.

**Guardrails:** `max_turns`, per-tool rate limits, timeout.

---

### Pattern 2: Plan-then-Execute

Before taking any action, the LLM generates an explicit plan. Each step is then executed (potentially by a cheaper model), and the plan can be revised based on results.

```
User: "Research privacy solutions for our L2 architecture"
  │
  ├─ Planning call (strong model):
  │     "Plan:
  │      1. Search dataset for L2 architecture constraints
  │      2. Web search for ZK-based privacy solutions
  │      3. Web search for L2-specific privacy implementations
  │      4. Cross-reference findings with our architecture
  │      5. Synthesize into report"
  │
  ├─ Execution (can be cheaper model per step):
  │     Step 1: dataset_search("L2 architecture") → results
  │     Step 2: web_search("ZK privacy solutions L2") → results
  │     Step 3: web_search("privacy L2 rollup implementations") → results
  │     Step 4: LLM cross-references (with all gathered data)
  │     Step 5: LLM synthesizes report
  │
  ├─ Plan revision (if step 2 reveals unexpected direction):
  │     "Revised plan: add step 2b — search for FHE-based approaches"
  │
  └─ Result: structured research report
```

**When to use:** Complex, multi-source tasks where quality matters more than speed. Research reports, market analysis, multi-tool workflows.

**Advantage over pure ReAct:** The model "thinks through" the entire task before acting, reducing myopic decisions and wasted tool calls.

---

### Pattern 3: Reflection / Self-Critique

After producing a result, the LLM evaluates its own output against the original request and known quality criteria. If the self-critique identifies gaps, the loop continues.

```
User: "Summarize last week's progress based on Trello and notes"
  │
  ├─ Generation pass: produces summary draft
  │
  ├─ Reflection pass:
  │     "Critique: The summary covers Trello tasks but does not mention
  │      the dataset notes from knowledge/work/. Also missing: comparison
  │      with the previous week's goals."
  │
  ├─ Improvement pass: gathers missing data, produces revised summary
  │
  └─ Result: comprehensive summary
```

**When to use:** Tasks where output quality is critical and a single pass typically misses aspects. Report writing, analysis, recommendations.

**Cost:** 2–3x the LLM calls of a single pass. Only justified for high-value outputs.

---

### Pattern 4: Multi-Agent Handoffs

Different parts of a task are handled by specialized agents with different prompts, tools, and constraints. Control transfers between agents mid-execution via handoffs.

```
User: "Research privacy solutions and create a Trello card with findings"
  │
  ├─ Researcher agent:
  │     - Has: web_search, dataset_search, dataset_read tools
  │     - Produces: research summary
  │     - Hands off to: Secretary agent
  │
  ├─ Secretary agent:
  │     - Has: trello_create_card, trello_list_boards tools
  │     - Receives: research summary from Researcher
  │     - Creates: Trello card draft
  │     - Returns: draft for user approval
  │
  └─ Result: research + Trello card (pending approval)
```

**When to use:** Tasks that span multiple domains requiring different expertise and tool access. This maps directly to Harle's agent roles (Researcher, Secretary, Specialist).

**Key constraint:** Each agent only accesses its own tools — the Researcher cannot write to Trello, the Secretary cannot run web searches. This is a security boundary.

---

### Pattern 5: Adaptive Planning with Tree Search

The most complex pattern. The agent generates multiple possible approaches, evaluates each one (possibly by executing the first few steps of each), and commits to the best path. This is the AI equivalent of "considering your options before acting."

```
User: "Find the best approach to reduce our transaction costs"
  │
  ├─ Generate 3 candidate strategies:
  │     A) Analyze current gas usage patterns
  │     B) Research alternative L2 solutions
  │     C) Optimize batch parameters
  │
  ├─ Evaluate each (quick exploration):
  │     A) Score: 0.7 — dataset has gas logs, feasible
  │     B) Score: 0.4 — would require migration analysis, expensive
  │     C) Score: 0.8 — config.yaml has batch params, quick win
  │
  ├─ Execute best path (C), with A as secondary:
  │     ... full execution of approach C ...
  │     ... then approach A for additional savings ...
  │
  └─ Result: actionable recommendations ranked by effort/impact
```

**When to use:** High-stakes decisions where the cost of a wrong approach is high. Rare in personal assistant use cases — more relevant for enterprise workflows.

---

## Harle-Specific Design Decisions

### 1. The Agent Runner Wraps the OpenAI SDK Runner

Harle does not reimplement the agentic loop. The OpenAI Agents SDK `Runner` handles the core loop (tool calls, handoffs, turn counting). Harle's `AgentRunner` wraps it to add:
- Harle-specific guardrails (tool allowlist enforcement, approval gates).
- Context assembly integration (feed the assembled context as the agent's instructions).
- Run logging (persist every turn, tool call, and decision to the `runs` table and vault).
- Cost tracking (token counting per turn, cumulative cost per run).

### 2. Context Assembly Happens Once, Before the Loop

The Context Assembler runs **before** the agentic loop starts. It produces the system prompt with P0 (prompts, policies) + P1 (search results) + P3 (memories) + P4 (conversation history). This system prompt becomes the agent's `instructions` parameter.

During the loop, the agent may gather additional information via tool calls — but the base context does not change mid-loop. This keeps context assembly deterministic and debuggable.

### 3. Tool Results Are Appendable Context

When the agent calls a tool (e.g., `trello_list_cards`), the result is appended to the conversation within the loop — the SDK handles this automatically. The agent sees tool results in subsequent turns without re-running context assembly.

### 4. Guardrails Are Layered

```
Layer 1 (SDK built-in):  max_turns, output validation
Layer 2 (Harle wrapper):  tool allowlist, approval gates, per-tool rate limits
Layer 3 (configuration):  timeout, token budget cap, cost threshold
```

Each layer operates independently. The SDK's `max_turns` catches runaway loops. Harle's tool allowlist prevents unauthorized tool access. The configuration timeout kills long-running tasks gracefully.

### 5. Streaming During Multi-Step Runs

During multi-step execution, the user sees:
- **Tool call notifications:** "Searching Trello..." / "Running web search..."
- **Intermediate status:** "Found 23 cards, analyzing..."
- **Final result:** The complete response streams word-by-word.

This prevents the "blank screen for 30 seconds" problem that makes single-call architectures feel broken for complex tasks.

### 6. Thinking Steps Are Encouraged via System Prompt

Rather than implementing Anthropic's Think Tool as a separate tool, Harle achieves the same effect by including instructions in the agent's system prompt:

```
Before calling any tool, briefly state (in your response) what you know so far,
what you still need, and why you are calling this specific tool. This helps
maintain reasoning coherence across multiple steps.
```

This produces visible reasoning traces in the run log without adding tool-call overhead. If this proves insufficient, a dedicated `think` tool can be added later (Level 4 in the plan).

---

## Incremental Implementation Plan

The plan is organized into seven levels. Each level is a **self-contained, deployable increment** — Harle works at every level, just with increasing capability. Each level builds on the previous one and should be completed before moving to the next.

---

### Level 0: Current State (baseline)

**What exists today:**

```
POST /run → ContextAssembler.assemble() → LLMProvider.generate() → Response
```

- Single LLM call per request.
- Context assembly with P0 (prompts, policies) + P1 (search results) + P4 (conversation history for chat).
- No tool calling, no agentic loop, no planning, no reflection.
- OpenAI Responses API (`client.responses.create()`).

**Limitations:**
- Cannot discover information mid-reasoning.
- Cannot interact with external services (Trello, web search) during a run.
- Every piece of context must be pre-loaded — wrong guesses by the Context Assembler directly degrade quality.

---

### Level 1: Basic Tool-Calling Loop

**Goal:** The LLM can call tools and see results. The simplest possible multi-step pattern.

**What changes:**
1. **Tool Module Layer foundations.** Create `BaseToolModule` and `ToolRegistry` (see [tools.md](./tools.md), Phases 1–2). Register the first two tools as a vault module: `dataset_search` (re-queries the dataset) and `dataset_read_file` (reads a specific file by path). These are read-only, low-risk tools that operate on local data.
2. **Switch from Responses API to Agents SDK.** Replace `client.responses.create()` with `Runner.run_sync()`. Define the agent with instructions (from Context Assembler) and the tool list from the registry.
3. **`max_turns` configuration.** Add `max_iterations` to `config.yaml` (default: 5 for Level 1). The SDK enforces this.
4. **Run logging per turn.** Extend the run logger to record each turn: what the LLM said, which tool it called, what the tool returned, how many tokens were used.

**What this enables:**
- The LLM can say "I need to read file X" and actually read it, instead of hoping the Context Assembler included it.
- Iterative search: if the first dataset search returns poor results, the LLM can refine its query and search again.

**Architecture:**

```
POST /run → ContextAssembler.assemble()
          → Agent(instructions=system_prompt, tools=[dataset_search, dataset_read])
          → Runner.run_sync(agent, user_message, max_turns=5)
               │
               ├─ Turn 1: LLM may call dataset_search → results appended
               ├─ Turn 2: LLM may call dataset_read → file content appended
               ├─ Turn 3: LLM produces final answer
               │
          → Log all turns
          → Response
```

**Estimated complexity:** Medium. Most of the work is plumbing the Agents SDK into the existing orchestrator and replacing the direct API call.

**What to watch out for:**
- The SDK creates its own OpenAI client — ensure the API key and model configuration flow through correctly.
- Tool functions must be synchronous or wrapped in `run_sync` properly.
- The system prompt from the Context Assembler becomes the agent's `instructions` — verify token counting still works correctly.

---

### Level 2: External Tools (Trello, Web Search)

**Goal:** The agent can interact with external services, with safety guardrails.

**What changes:**
1. **Web Search and Trello modules.** Register `WebSearchModule` and `TrelloModule` with the Tool Registry (see [tools.md](./tools.md), Phases 2 and 6). Each module follows the `BaseToolModule` interface — lifecycle, tool functions, skills, configuration.
2. **Web search tools.** `search_web`, `search_news` via Tavily or Bing API — returns top 3–5 results with snippets.
3. **Trello tools.** `search_cards`, `get_card` (read-only first).
4. **Tool allowlist enforcement.** Before each tool call, the Tool Registry checks: (a) is this tool allowed for the active agent role? (b) does it require approval? (c) do inputs pass security constraints?
5. **Approval flow for write tools.** When a tool with `requires_approval=True` is called in `propose` mode, the run pauses, sends the proposed action to the user via the API, and resumes after approval/denial. Not needed for Level 2 (all tools are read-only) but the infrastructure is built.
6. **`max_turns` increase.** Raise default to 10 — external tool calls typically need more turns than dataset-only queries.

**What this enables:**
- "Find stalled Trello tasks" actually reads from Trello during the run.
- "Research X" performs live web searches and synthesizes results.
- The agent decides which tools to call and in what order, based on the task.

**Architecture:**

```
POST /run → ContextAssembler.assemble() + registry.get_skills_for_tools()
          → registry.get_agent_tools(filtered_tool_names)
          → Agent(instructions=system_prompt + skills, tools=filtered_tools)
          → Runner.run_sync(agent, user_message, max_turns=10)
               │
               ├─ Turn 1: LLM calls search_web("privacy L2 solutions")
               │          Registry checks: search_web allowed for researcher? Yes.
               │          Execute → results appended
               ├─ Turn 2: LLM calls dataset_search("L2 architecture")
               │          Execute → results appended
               ├─ Turn 3: LLM synthesizes into answer
               │
          → Log all turns with tool details
          → Response
```

**Estimated complexity:** Medium-high. The Tool Module Layer infrastructure (registry, permissions, skills) is built in earlier phases (see [tools.md](./tools.md)). External API integrations (web search, Trello) each need error handling, retry logic, and rate limiting.

---

### Level 3: Plan-then-Execute

**Goal:** For complex tasks, the agent first creates a plan, then executes it step by step. Plans can be revised mid-execution.

**What changes:**
1. **Task complexity classifier.** A lightweight check (keyword rules + optional cheap LLM call) that determines whether a request needs planning or can be handled reactively. Simple requests ("What is X?") skip planning. Complex requests ("Research X, compare with Y, produce a report") trigger the planner.
2. **Planning step.** Before the main agentic loop, a separate LLM call generates a structured plan:
   ```
   Plan:
   1. [search] Query dataset for L2 architecture constraints
   2. [web_search] Find ZK privacy solutions for rollups
   3. [web_search] Find FHE-based privacy approaches
   4. [synthesize] Compare approaches against our constraints
   5. [output] Structured comparison report
   ```
3. **Plan injection.** The plan is prepended to the agent's instructions for the execution loop. The agent follows the plan but can deviate if it discovers something unexpected.
4. **Plan revision.** After each major step (or every N turns), the agent can emit a "revised plan" if the original plan no longer makes sense. Revisions are logged.
5. **Two-model optimization (optional).** The planning call can use a stronger model (e.g., `gpt-4o`) while execution uses a cheaper model (e.g., `gpt-4o-mini`). This trades slightly higher planning cost for significantly lower execution cost.

**What this enables:**
- Complex research tasks produce better results because the agent "thinks through" the full approach before starting.
- Users can see the plan before execution begins and request changes.
- Cost optimization: cheap model for routine steps, expensive model for planning.

**Architecture:**

```
POST /run → ContextAssembler.assemble()
          → ComplexityClassifier.classify(request)
              │
              ├─ Simple → direct to Runner (Level 2 flow)
              │
              └─ Complex → PlanningStep:
                    │
                    ├─ LLM call: "Given this context and request, create a plan"
                    ├─ Plan validation (parseable, reasonable step count)
                    ├─ Optional: show plan to user for approval
                    │
                    └─ ExecutionLoop:
                          Agent(instructions=system_prompt + plan, tools=filtered_tools)
                          Runner.run_sync(agent, user_message, max_turns=15)
                             │
                             ├─ Follows plan steps
                             ├─ May revise plan based on discoveries
                             │
                    → Log plan + revisions + all turns
                    → Response
```

**Estimated complexity:** Medium. The planner is a single additional LLM call with structured output parsing. The complexity classifier can start as simple keyword rules.

---

### Level 4: Reflection and Self-Critique

**Goal:** For high-value outputs (reports, recommendations), the agent evaluates its own result and improves it before returning.

**What changes:**
1. **Reflection trigger.** Certain task types (configurable) trigger a reflection pass after the initial result is generated. Examples: any task tagged as "research", "report", or "analysis"; any run that used 3+ tool calls; any request from the Researcher role.
2. **Reflection prompt.** A separate LLM call with the original request, the agent's result, and a reflection instruction:
   ```
   Review this result against the original request. Check:
   - Does it answer the actual question?
   - Are there gaps in the data used?
   - Are the conclusions supported by the evidence?
   - What would make this answer significantly better?
   If improvements are needed, list them specifically.
   ```
3. **Improvement loop.** If the reflection identifies concrete improvements (not just "looks good"), the agent gets one more pass to incorporate them. Maximum 1 reflection cycle (to control costs).
4. **Think tool (optional).** If system-prompt-based thinking (Level 1) proves insufficient, add a dedicated `think` tool — a no-op tool that gives the model a structured scratchpad. The model calls `think(reasoning="I've gathered X and Y, but I still need Z because...")` and the tool returns nothing. This creates an explicit reasoning trace in the run log.

**What this enables:**
- Research reports are significantly higher quality — the model catches its own oversights.
- Run logs show what the agent thought was good/bad about its own output — invaluable for prompt tuning.
- The think tool makes reasoning visible without cluttering the final output.

**Architecture:**

```
ExecutionLoop produces initial_result
    │
    ├─ ReflectionTrigger: should this result be reviewed?
    │     │
    │     ├─ No → return initial_result
    │     │
    │     └─ Yes → ReflectionCall:
    │           LLM evaluates initial_result against request
    │           │
    │           ├─ "No improvements needed" → return initial_result
    │           │
    │           └─ "Improvements: [list]" → ImprovementPass:
    │                 LLM incorporates improvements (1 pass max)
    │                 → return improved_result
    │
    → Log reflection analysis
    → Response
```

**Estimated complexity:** Low-medium. Reflection is just an additional LLM call with a well-crafted prompt. The main work is deciding when to trigger it (to avoid doubling cost on every request).

---

### Level 5: Multi-Agent Handoffs

**Goal:** Different agent roles collaborate on a single task. One agent can hand off to another mid-execution.

**What changes:**
1. **Agent definitions from vault.** Each agent role (Researcher, Secretary, Specialist) is defined as an Agents SDK `Agent` object with role-specific instructions (loaded from `prompts/*.md`), tools (filtered by the Tool Registry), and handoff targets.
2. **Handoff declarations.** Each agent declares which other agents it can hand off to:
   - Secretary → Researcher (for research subtasks)
   - Researcher → Secretary (to create Trello cards with findings)
   - Specialist → Secretary, Researcher (to delegate maintenance tasks)
3. **Shared conversation context.** When a handoff occurs, the conversation history (including tool results from the first agent) carries over. The new agent sees everything the previous agent did.
4. **Router integration.** The Router (currently hardcoded to "researcher") is wired up. It determines the starting agent based on the request. Handoffs allow mid-run role switches that the Router cannot predict upfront.
5. **Handoff logging.** Each handoff is logged: which agent handed off, to whom, with what context summary, and why (the handing-off agent's stated reason).

**What this enables:**
- "Research privacy solutions and create a Trello card" — Researcher does the research, hands off to Secretary for Trello interaction.
- "Analyze agent performance and update the prompts" — Specialist reviews logs, then delegates prompt updates to itself with write permissions.
- Natural task decomposition: the LLM decides when a subtask needs a specialist, rather than the user specifying everything upfront.

**Architecture:**

```
POST /run → Router.route(request)
          → ContextAssembler.assemble(agent_role=routed_role)
          → Agent definitions loaded (with handoff targets)
          → Runner.run_sync(starting_agent, user_message, max_turns=15)
               │
               ├─ Turns 1–3: Researcher agent works
               │     Calls web_search, dataset_search
               │     Produces research summary
               │
               ├─ Turn 4: Researcher hands off to Secretary
               │     Conversation history carries over
               │     Secretary agent activates with its own tools
               │
               ├─ Turns 5–6: Secretary creates Trello card draft
               │     Calls trello_create_card (requires approval)
               │     → Approval gate pauses run
               │     → User approves
               │     → Card created
               │
               ├─ Turn 7: Secretary produces final summary
               │
          → Log all turns + handoff details
          → Response
```

**Estimated complexity:** High. Multi-agent coordination introduces new failure modes: handoff loops, context loss at boundaries, conflicting tool access. The Router module needs to be implemented.

---

### Level 6: Adaptive Strategy Selection

**Goal:** The orchestrator automatically selects the best reasoning strategy (reactive, planned, reflective, multi-agent) based on the task.

**What changes:**
1. **Strategy selector.** A lightweight classifier (rules + optional LLM call) that chooses the reasoning strategy before execution begins:

   | Strategy | When selected | Example |
   |---|---|---|
   | **Direct** (Level 1–2) | Simple queries, single-tool tasks | "What's in my Trello 'To Do' list?" |
   | **Planned** (Level 3) | Multi-step, multi-source tasks | "Research X and produce a report" |
   | **Reflective** (Level 4) | High-value outputs, analysis tasks | "Analyze our architecture against competitors" |
   | **Multi-agent** (Level 5) | Cross-domain tasks | "Research X, then create a task for Y" |
   | **Planned + Reflective** | Complex, high-value outputs | "Prepare a comprehensive market analysis" |

2. **Strategy configuration per agent role.** Agent prompt files can specify preferred strategies:
   ```yaml
   # prompts/researcher.md frontmatter
   preferred_strategy: planned+reflective
   max_turns: 20
   reflection_enabled: true
   ```
3. **User override.** The CLI supports a `--strategy` flag for explicit control: `harle --strategy=planned "Research privacy solutions"`.
4. **Cost-aware selection.** The strategy selector considers the estimated cost of each strategy (based on historical averages for similar tasks) and warns the user if the selected strategy is expensive.

**What this enables:**
- Simple tasks are fast and cheap (no unnecessary planning or reflection).
- Complex tasks automatically get the full treatment (planning + execution + reflection).
- Users can override when they know what they want.

**Estimated complexity:** Medium. The selector itself is simple (rules-based with LLM fallback, similar to the Router). The complexity is in having Levels 1–5 all working reliably so the selector has strategies to choose from.

---

### Level 7: Parallel Execution and Advanced Orchestration

**Goal:** Independent subtasks execute in parallel. The orchestrator can explore multiple approaches and pick the best.

**What changes:**
1. **Parallel tool calls.** When the plan identifies independent steps (e.g., "search dataset" and "search web" simultaneously), they execute in parallel using `asyncio.gather()`. The Agents SDK supports this — multiple tool calls in a single turn can run concurrently.
2. **Parallel agent execution.** For multi-agent tasks, independent agents can run simultaneously. Example: Researcher searches the web while Secretary reads Trello, then results are merged.
3. **Branch-and-merge.** For exploratory tasks, the orchestrator can spawn multiple approaches in parallel, evaluate intermediate results, and merge the best findings. This is a simplified version of tree search.
4. **Progressive streaming.** During parallel execution, results stream to the user as they arrive. The user sees "Web search complete... Dataset search complete... Synthesizing..." in real-time.
5. **Adaptive concurrency limits.** Configuration controls how many parallel tool calls and agent runs are allowed simultaneously (to control API rate limits and costs).

**What this enables:**
- Significantly faster execution for multi-source tasks (parallel web + dataset + Trello queries).
- Higher quality for open-ended research (explore multiple angles, keep the best).
- Better user experience (progressive results instead of long waits).

**Estimated complexity:** High. Async coordination, error handling for partial failures (some branches succeed, others fail), and result merging are non-trivial. This is an optimization over Levels 1–6, not a prerequisite.

---

## Implementation Dependency Graph

```
Level 0: Current state (single LLM call)
   │
   └──→ Level 1: Tool-calling loop (Agents SDK integration)
           │
           └──→ Level 2: External tools (Web Search, Trello, Tool Module Layer)
                   │
                   ├──→ Level 3: Plan-then-Execute
                   │       │
                   │       └──→ Level 4: Reflection & Self-Critique
                   │
                   └──→ Level 5: Multi-Agent Handoffs (depends on Router)
                           │
                           └──→ Level 6: Adaptive Strategy Selection
                                   │
                                   └──→ Level 7: Parallel Execution
```

Levels 3 and 5 can be developed in parallel after Level 2 — they are independent of each other. Level 6 requires both. Level 7 is an optimization that can be tackled last.

---

## Cost and Latency Projections

| Level | LLM calls per run (typical) | Estimated cost per run | Latency (typical) |
|---|---|---|---|
| **0** (current) | 1 | $0.001–0.01 | 1–5 sec |
| **1** (tool loop) | 2–4 | $0.003–0.03 | 3–15 sec |
| **2** (external tools) | 3–6 | $0.005–0.05 | 5–25 sec |
| **3** (plan + execute) | 4–10 | $0.01–0.10 | 10–45 sec |
| **4** (reflection) | +1–2 per run | +$0.005–0.02 | +3–10 sec |
| **5** (multi-agent) | 5–15 | $0.01–0.15 | 10–60 sec |
| **6** (adaptive) | same as 1–5 | same as 1–5 | same + ~1 sec |
| **7** (parallel) | same total calls | same cost | 30–50% faster |

Costs assume GPT-4o-mini for execution ($0.15/1M input, $0.60/1M output) and GPT-4o for planning ($2.50/1M input, $10/1M output). Personal use at 20–50 runs/day is well under $5/month at Level 3.

---

## Key Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **Runaway loops** (agent calls tools endlessly) | High cost, frozen UX | `max_turns` + timeout + per-tool rate limits. Start with conservative limits (5 turns at Level 1) and increase gradually. |
| **Tool call hallucination** (LLM invents plausible but wrong tool parameters) | Wrong data returned, silent failures | Schema-based parameter validation in the Tool Registry + security constraints (see [tools.md](./tools.md)). Log every tool call for audit. Best models (GPT-4o family) have low tool-call hallucination rates. |
| **Context window overflow** during multi-step runs | Degraded quality in later turns | The Agents SDK manages conversation truncation. Monitor per-run token usage. Long runs may need conversation compression. |
| **Plan quality** (LLM produces a bad plan) | Wasted execution, wrong results | Plan validation before execution. User approval for expensive plans. Revision mechanism catches bad plans mid-execution. |
| **Handoff confusion** (wrong agent activated) | Tool access violations, wrong approach | Strict tool allowlists per agent. Handoff logging. Start with explicit handoff rules (no open-ended "hand off to whoever you think is best"). |
| **Cost explosion** at higher levels | Unexpectedly expensive runs | Per-run cost tracking and configurable thresholds. Warn user when estimated cost exceeds limit. Default to cheaper strategies for routine tasks. |

---

## Summary

Multi-step reasoning transforms Harle from a context-stuffing chatbot into a genuine agent that can plan, act, observe, reflect, and collaborate. The incremental plan ensures that each level adds capability without requiring all subsequent levels — Harle is useful at every stage.

The recommended starting point is **Level 1** (basic tool-calling loop with the Agents SDK), which unblocks everything else. The highest-impact early levels are **Level 2** (external tools) and **Level 3** (planning), which together cover ~80% of the use cases described in the current goal (Researcher, Secretary, Specialist roles).

The industry consensus — from OpenAI's SDK to Anthropic's Think Tool to LangChain's pattern taxonomy — is that **planning before acting** and **explicit reasoning traces** are the two highest-leverage improvements over naive tool-calling loops. Harle's incremental plan reflects this: tool loop first, planning second, reflection third, multi-agent collaboration fourth.
