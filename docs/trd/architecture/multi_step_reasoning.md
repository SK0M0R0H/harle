---
title: "Multi-Step Reasoning — Design & Incremental Implementation Plan"
tags: [orchestrator, multi-step-reasoning, agentic-loop, tool-use, planning, react, agents]
context: global
last_updated: 2026-03-21
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

**Why wrapping is feasible — what the SDK Runner does internally:**

The `Runner` class (specifically the internal `AgentRunner.run()` method in the SDK) implements the entire agentic loop as a `while True` loop that repeatedly calls `run_single_turn()`. Each turn invokes the LLM, receives a response, and classifies the result into one of four `NextStep` types that determine what happens next:

```
┌──────────────────────────────────────────────────────────────┐
│  AgentRunner.run() — the while True loop                     │
│                                                              │
│  Each iteration:                                             │
│    1. Enforce max_turns (raise MaxTurnsExceeded if exceeded)  │
│    2. Resolve tools, handoffs, output schema for current agent│
│    3. Call run_single_turn() → LLM invocation + tool execution│
│    4. Classify response into NextStep:                        │
│       ┌───────────────────────┐                               │
│       │ NextStepRunAgain      │→ Tool calls executed, results │
│       │                       │  appended to conversation.    │
│       │                       │  Loop continues.              │
│       ├───────────────────────┤                               │
│       │ NextStepHandoff       │→ Swap current_agent to the    │
│       │                       │  handoff target. Carry over   │
│       │                       │  conversation. Loop continues.│
│       ├───────────────────────┤                               │
│       │ NextStepFinalOutput   │→ Run output guardrails.       │
│       │                       │  Return RunResult.            │
│       │                       │  Loop terminates.             │
│       ├───────────────────────┤                               │
│       │ NextStepInterruption  │→ A tool requires approval.    │
│       │                       │  Pause loop, return RunResult │
│       │                       │  with interruption data.      │
│       │                       │  Caller can resume later.     │
│       └───────────────────────┘                               │
│    5. Append model response + tool results to generated_items │
│    6. Persist session items if session is enabled              │
└──────────────────────────────────────────────────────────────┘
```

The SDK manages the following responsibilities entirely inside this loop — none of which Harle needs to reimplement:

| Responsibility | What the SDK does |
|---|---|
| **Turn counting** | Increments a counter each iteration, raises `MaxTurnsExceeded` when `current_turn > max_turns` (or calls a custom error handler if provided). |
| **Tool resolution and execution** | Calls `get_all_tools()` to resolve the agent's tool list, executes tool calls returned by the LLM, appends results as `tool_call_output_item` entries in the conversation. |
| **Handoff mechanics** | When the LLM emits a handoff, swaps `current_agent`, optionally filters/nests the conversation history for the new agent, and continues the loop. |
| **Input/output guardrails** | Runs input guardrails on the first turn (optionally in parallel with the model call), output guardrails when final output is produced. |
| **Conversation state** | Three strategies — manual (`result.to_input_list()`), SDK sessions (`SQLiteSession`, etc.), or OpenAI server-managed (`conversation_id`/`previous_response_id`) — all handled transparently. |
| **Tracing** | Creates trace and agent spans automatically. Every turn, tool call, and handoff is recorded. |
| **Interruption and resume** | When a tool requires human approval, the loop pauses and returns a `RunResult` with interruption data. The same `RunState` can be passed back to `Runner.run()` to resume exactly where it left off. |
| **Error recovery** | Retries `conversation_locked` errors with backoff, cleans up async resources on cancellation, disposes computer tools on exit. |

**What the SDK does *not* manage — the wrapping surface:**

The Runner is designed with clean input/output boundaries that make wrapping straightforward:

- **Inputs:** An `Agent` object (instructions, tools, handoffs) + user input + `RunConfig`. Harle controls what goes into these before calling the Runner.
- **Outputs:** A `RunResult` containing all generated items, model responses, guardrail results, and the final output. Harle can inspect and log everything after the Runner returns.
- **Hooks:** The `RunHooks` interface provides lifecycle callbacks (`on_agent_start`, `on_agent_end`, `on_tool_start`, `on_tool_end`, `on_handoff`) that fire at each stage without modifying the loop itself.

This means Harle's wrapper operates **exclusively at the boundaries** — it prepares the Agent and RunConfig before the loop, and processes the RunResult after:

```python
# Simplified view of how Harle wraps the SDK Runner

class HarleAgentRunner:
    async def run(self, request, context):
        # --- BEFORE the loop (Harle's domain) ---
        system_prompt = await self.context_assembler.assemble(request)
        allowed_tools = self.tool_registry.get_tools_for_role(request.agent_role)
        agent = Agent(
            name=request.agent_role,
            instructions=system_prompt,
            tools=allowed_tools,
            handoffs=self.get_handoff_targets(request.agent_role),
        )
        run_config = RunConfig(
            model=self.config.model,
            tracing_disabled=not self.config.tracing_enabled,
        )

        # --- THE loop (SDK's domain — untouched) ---
        result = await Runner.run(
            agent, request.message,
            max_turns=self.config.max_iterations,
            run_config=run_config,
        )

        # --- AFTER the loop (Harle's domain) ---
        await self.run_logger.log_run(result)
        self.cost_tracker.record(result.raw_responses)
        return result.final_output
```

The SDK does not know or care about Harle's tool allowlists, cost budgets, vault logging, or context assembly. And Harle does not need to understand the SDK's internal turn management, conversation tracking, or guardrail execution. Each layer handles its own concerns. This is why wrapping — rather than reimplementing or forking — is the right approach.

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

### 6. Thinking Steps Are Encouraged via System Prompt (upgraded in Level 4)

Harle includes instructions in the agent's system prompt to encourage explicit reasoning:

```
Before calling any tool, briefly state (in your response) what you know so far,
what you still need, and why you are calling this specific tool. This helps
maintain reasoning coherence across multiple steps.
```

This produces visible reasoning traces in the run log without adding tool-call overhead. **Level 4 upgrades this** with a dedicated `think` tool — a no-op `function_tool` that gives the model a structured scratchpad. The think tool creates explicit reasoning traces in etrace spans without mixing reasoning into the final output. The system-prompt instruction remains as a complementary baseline. See [Level 4, §4.4](#44-think-tool) for the full design.

---

## Incremental Implementation Plan

The plan is organized into seven levels. Each level is a **self-contained, deployable increment** — Harle works at every level, just with increasing capability. Each level builds on the previous one and should be completed before moving to the next.

---

### Level 0: Current State (baseline)

**What exists today:**

```
POST /chat → ContextAssembler.assemble() → LLMProvider.generate() → Response
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

### Level 1: Basic Tool-Calling Loop ✅ IMPLEMENTED

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
POST /chat → ContextAssembler.assemble()
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

### Level 2: External Tools (Web Search) ✅ IMPLEMENTED

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
POST /chat → ContextAssembler.assemble() + registry.get_skills_for_tools()
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
POST /chat → ContextAssembler.assemble()
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

**Goal:** For high-value outputs (reports, analysis, research), the agent evaluates its own result and improves it before returning. Reflection is opt-in and configurable so cheap/simple requests stay unaffected.

#### Research: State-of-the-art reflection patterns

Review of 2025–2026 approaches to reflection in agentic systems (OpenAI Agents SDK, Anthropic's Think Tool, LangGraph/LangChain Reflexion, academic research on LLM self-correction) surfaces five findings relevant to Harle:

1. **Separate generation from evaluation.** A distinct critic/reflection call outperforms inline "review yourself" instructions. When the same context window generates and evaluates, models tend to rubber-stamp their own work. A dedicated reflection call with a fresh system prompt and the draft as user content forces genuine evaluation (Zylos Research 2026, AAIA Agentic AI Insights, LangGraph reflection agent pattern).

2. **Bound the loop.** Every production reflection system caps iterations. The consensus is 1–2 reflection cycles maximum — beyond that, quality plateaus while cost grows linearly. LangGraph's `langgraph-reflection` library defaults to 1 reflect-and-revise cycle. Harle caps at **1 improvement pass after 1 reflection call** (2 extra LLM calls worst case).

3. **External verification beats pure introspection.** Research shows that asking a model to self-correct reasoning without external feedback can *decrease* accuracy. However, comparing a draft answer against the **original request** and explicit quality criteria is a form of verification (the "reference" is the request), not pure introspection. This is the pattern that works — and it matches Harle's use case.

4. **Reserve reflection for high-value outputs.** Reflection adds 2–3x LLM cost and 3–10 seconds of latency. Applying it to "What time is it?" is waste. Every production system gates reflection behind a trigger: task type, complexity score, explicit user opt-in, or tool-use count. Harle's existing complexity classifier (Level 3) provides a natural signal.

5. **Think tool improves multi-step coherence.** Anthropic's think tool (March 2025) — a no-op tool that gives the model a scratchpad between tool calls — significantly improves quality on long tool chains and policy-heavy tasks. It creates explicit reasoning traces without cluttering final output. The OpenAI Agents SDK does not provide a built-in think tool but supports it trivially via `function_tool`. Harle's system-prompt thinking instruction (Level 1, Design Decision 6) provides partial coverage; a dedicated tool is the upgrade path.

**Minimal viable pattern for Harle:** Post-execution reflection pass (1 LLM call) with configurable trigger, at most 1 improvement pass (1 LLM call with tools), and an optional think tool (no-op `function_tool` registered alongside other tools). Total worst-case overhead: 2 additional LLM calls per run.

**Key pitfall to avoid:** Unbounded reflection cycles. The hard limit of 1 reflection + 1 improvement is non-negotiable. The improvement pass MUST NOT trigger another reflection check.

---

#### 4.1 Reflection trigger

Reflection runs **after** the execution loop (Level 1–3) produces a result. The trigger is a deterministic function — no LLM call needed.

**Trigger rules** (OR logic — any matching rule triggers reflection):

| Rule | Condition | Rationale |
|------|-----------|-----------|
| **Disabled globally** | `HARLE_REFLECTION_ENABLED` is `False` | Kill switch — returns `False` immediately, no further evaluation. |
| **Minimum tool-call threshold** | Execution used ≥ `HARLE_REFLECTION_MIN_TOOL_CALLS` tool calls (default: 3) | Runs with many tool calls are complex enough to benefit; simple lookups skip. |
| **Task-type keywords** | User message contains any keyword in `HARLE_REFLECTION_TRIGGER_KEYWORDS` (default: `["research", "report", "analysis", "compare", "evaluate", "review", "summarize"]`) | Knowledge-intensive tasks where output quality matters. |
| **Planned runs** | `routing_method == "planned"` (Level 3 classified the request as complex) | If the planner thought it was complex, reflection is warranted. |
| **Role-based** | Agent role is in `HARLE_REFLECTION_TRIGGER_ROLES` (default: `["researcher"]`) | Certain roles always benefit from reflection. Currently one role; future-proofs for Level 5. |

When `HARLE_REFLECTION_TRIGGER_KEYWORDS` or `HARLE_REFLECTION_TRIGGER_ROLES` is set to an empty list, that rule is disabled. Operators can narrow the trigger to tool-call count only, or widen it to always-on, without code changes.

**Function signature** (mirrors `classify_complexity`):

```python
def should_reflect(
    *,
    user_message: str,
    tools_called: list[str],
    routing_method: str,
    agent_role: str,
    config: ReflectionConfig,
) -> tuple[bool, str]:
    """Determine whether a reflection pass should run.

    Returns:
        Tuple of (should_reflect, trigger_reason). trigger_reason
        is a short string for logging (e.g. "tool_count",
        "keyword:research", "planned", "role:researcher").
    """
```

---

#### 4.2 Reflection call

When triggered, a dedicated LLM call evaluates the execution result against the original request.

**Mechanics:**

- **No tools.** The reflection call is a pure assessment with no tool access. It receives all the information it needs (original request + draft result) as input.
- **Separate system prompt.** A reflection-specific instruction, not the full context-assembled prompt. This keeps the reflection call lightweight and focused.
- **Model.** `HARLE_REFLECTION_MODEL` (default: same as `HARLE_LLM_MODEL`). Operators can use a cheaper model for reflection.
- **Implementation.** A single `Runner.run_sync` call with an `Agent` that has no tools and `max_turns=1`. Using the Agent/Runner keeps the pattern consistent with the rest of the pipeline and gives tracing for free.

**Reflection prompt shape:**

```
You are a quality reviewer for an AI assistant's output. Your task is to evaluate
whether the assistant's response adequately addresses the user's request.

## Original user request

{user_message}

## Assistant's draft response

{draft_result}

## Evaluation criteria

Review the draft response against the original request. Check each criterion:

1. **Completeness:** Does it answer the actual question? Are all parts of the request
   addressed?
2. **Evidence:** Are claims supported by data gathered during the run? Are there
   unsupported assertions?
3. **Gaps:** Is there information the user likely needs that was not included? Were
   there tools available that should have been called but were not?
4. **Accuracy:** Are there factual inconsistencies or contradictions within the
   response?
5. **Clarity:** Is the response well-structured and easy to follow?

## Output format

Respond with a JSON object:

    {"verdict": "pass" | "improve",
     "assessment": "Brief overall assessment (1-2 sentences)",
     "improvements": ["specific improvement 1", "specific improvement 2", ...]}

If the response is adequate, set verdict to "pass" and leave improvements empty.
If improvements are needed, set verdict to "improve" and list SPECIFIC, ACTIONABLE
improvements. Do not suggest improvements that would require information the assistant
cannot obtain.
```

**Verdict parsing:**

The reflection output is parsed as JSON. If parsing fails, or if `verdict` is not `"improve"`, the original result is returned unchanged. Malformed reflection output is logged as a warning and treated as a pass — **fail-open, not fail-closed**. This ensures reflection bugs never block the user from getting a result.

---

#### 4.3 Improvement loop

When the reflection verdict is `"improve"` with a non-empty `improvements` list, one improvement pass runs.

**Mechanics:**

- **One pass only.** The improvement pass does NOT trigger another reflection check. This is the hard limit that prevents unbounded cycles.
- **Tools available.** The improvement agent has the same tools as the original execution agent. This lets it call tools to fill gaps identified by reflection (e.g., "the summary omits dataset notes — search for them").
- **Max turns.** `HARLE_REFLECTION_IMPROVEMENT_MAX_TURNS` (default: same as `HARLE_MAX_ITERATIONS`). The improvement pass gets its own turn budget.
- **Instructions.** The improvement agent receives the original execution instructions plus the reflection feedback injected as a preamble:

```
## Reflection feedback — improvements required

The following improvements were identified by quality review. Incorporate
them into your response:

{numbered list of improvements from reflection}

## Original user request

{user_message}

## Your previous draft

{draft_result}

Produce an improved version of the response that addresses the feedback above.
You may call tools if additional information is needed.
```

- **Result.** The improvement pass output replaces the original draft as the final result. If the improvement pass fails (e.g., `MaxTurnsExceeded`), the original draft is returned with a log entry noting the improvement failure.

**Flow:**

```
Execution result (draft)
    │
    ├── should_reflect() → False → return draft
    │
    └── should_reflect() → True
            │
            ├── reflection_call(user_message, draft)
            │       │
            │       ├── verdict: "pass" → return draft
            │       │
            │       └── verdict: "improve", improvements: [...]
            │               │
            │               └── improvement_pass(user_message, draft, improvements, tools)
            │                       │
            │                       ├── success → return improved_result
            │                       │
            │                       └── failure → return draft (log failure)
            │
            └── reflection_call fails → return draft (log error)
```

---

#### 4.4 Think tool

**Decision: implement as a `function_tool`.**

The system-prompt thinking instruction (Level 1, Design Decision 6) is partially effective but has limitations: (a) models sometimes skip the thinking step under token pressure, (b) thinking text mixed into the final response clutters the output, (c) there is no structured way to extract reasoning traces for logging.

A dedicated think tool solves all three: the model calls `think(reasoning="...")` explicitly, the tool returns nothing (no-op), and the `reasoning` parameter is captured in the tool call trace.

**Implementation:**

```python
@function_tool
def think(reasoning: str) -> str:
    """Use this tool to think through a problem step by step.

    Call this tool before making decisions, between tool calls when
    you need to reason about results, or when facing a complex
    judgment. The reasoning is logged but does not appear in the
    final response.

    Args:
        reasoning: Your step-by-step thinking about the problem.
    """
    return ""
```

**Registration:**

- Registered via a new `ThinkToolModule` in `harle/tools/think/` (following the `BaseToolModule` pattern).
- Always available when the agent runner is active — no role-based filtering. The think tool is a reasoning primitive, not a domain tool.
- Appears in `tools_called` logs when used (tool name: `think`).
- `HARLE_THINK_TOOL_ENABLED` config key (default: `True`) for operators who want to disable it (e.g., to save tool-definition tokens in the prompt).

**Trace integration:**

The tool registry's `_make_traced_tool()` wrapper already creates etrace spans for every tool call. The think tool's `reasoning` parameter is captured as a span attribute, making it visible in execution traces without additional work.

**Impact on tool count:** Adds 1 tool definition to every agent prompt (~50 tokens). Minimal impact on context budget.

---

#### 4.5 Logging

Reflection metadata integrates with the existing run logging path at three levels.

**Vault (result file):**

A `## Reflection` section is appended to the vault result body, after the existing `## Plan` section (if present):

```markdown
## Reflection

**Triggered:** yes
**Trigger reason:** tool_count (5 tool calls ≥ threshold 3)
**Verdict:** improve
**Assessment:** The summary covers Trello tasks but omits dataset notes.
**Improvements applied:**
1. Added dataset notes from knowledge/work/
2. Included comparison with previous week's goals
**Improvement pass:** completed (3 turns, 1 tool call)
```

When reflection was triggered but the verdict was "pass," the section records that reflection ran but found no improvements needed. When reflection was not triggered, the section is omitted (no noise in logs for simple runs).

**DB (runs table):**

Two new nullable columns on the `runs` table:

| Column | Type | Description |
|--------|------|-------------|
| `reflection_triggered` | `Boolean` | `True` if `should_reflect()` returned `True`; `NULL` for runs before this feature. |
| `reflection_improved` | `Boolean` | `True` if the improvement pass ran and succeeded; `NULL` or `False` otherwise. |

These columns enable queries like "what percentage of runs trigger reflection?" and "how often does reflection lead to improvements?" — essential for tuning trigger thresholds and evaluating prompt quality.

**API (RunResponse):**

Two new optional fields:

```python
reflection_triggered: bool | None = None
reflection_improved: bool | None = None
```

**etrace spans:**

| Span | Level | Module | Attributes |
|------|-------|--------|------------|
| `Reflection trigger evaluated` | DETAIL | orchestrator | `triggered=True/False`, `reason="tool_count"/"keyword"/"planned"/"role"` |
| `Reflection call` | STEP | orchestrator | `verdict="pass"/"improve"`, `improvements_count=N` |
| `Improvement pass` | STEP | orchestrator | `turns_used=N`, `tools_called=[...]`, `status="completed"/"failed"` |

---

#### 4.6 Configuration

All new config keys, following the existing `HARLE_` prefix convention and resolution order (YAML → env var → default):

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `HARLE_REFLECTION_ENABLED` | `bool` | `True` | Master switch for reflection. `False` disables all reflection. |
| `HARLE_REFLECTION_MODEL` | `str \| None` | `None` | Model for the reflection call. `None` = same as `HARLE_LLM_MODEL`. |
| `HARLE_REFLECTION_MIN_TOOL_CALLS` | `int` | `3` | Minimum tool calls in execution to trigger reflection via tool-count rule. |
| `HARLE_REFLECTION_TRIGGER_KEYWORDS` | `list[str]` | `["research", "report", "analysis", "compare", "evaluate", "review", "summarize"]` | Keywords in user message that trigger reflection. Empty list disables keyword rule. |
| `HARLE_REFLECTION_TRIGGER_ROLES` | `list[str]` | `["researcher"]` | Agent roles that always trigger reflection. Empty list disables role rule. |
| `HARLE_REFLECTION_IMPROVEMENT_MAX_TURNS` | `int \| None` | `None` | Max turns for the improvement pass. `None` = same as `HARLE_MAX_ITERATIONS`. |
| `HARLE_THINK_TOOL_ENABLED` | `bool` | `True` | Register the think tool for agent runs. |

List-type config values are stored as YAML lists in the config file and as comma-separated strings in environment variables.

---

#### Architecture (full Level 4 flow)

Shows how reflection wraps the existing Level 1–3 execution:

```
POST /chat → ContextAssembler.assemble()
          → registry.get_agent_tools() (includes think tool when enabled)
          → run_agent_execution(...)
               │
               ├─ [Level 3] Planning (if complex)
               │     classify_complexity → generate_plan → validate → inject
               │
               ├─ [Level 1–2] Execution Loop
               │     Agent(instructions, tools=[..., think], model)
               │     Runner.run_sync(agent, user_message, max_turns=N)
               │        │
               │        ├─ Turn 1: LLM may call think(reasoning="...") → ""
               │        ├─ Turn 2: LLM calls search_web("...") → results
               │        ├─ Turn 3: LLM calls think(reasoning="...") → ""
               │        ├─ Turn 4: LLM produces draft result
               │        │
               │     → extract_run_metadata(result) → tools_called, turns_used
               │
               ├─ [Level 4] Reflection
               │     should_reflect(user_message, tools_called, routing_method,
               │                    role, config) → (triggered, reason)
               │        │
               │        ├─ False → skip
               │        │
               │        └─ True → reflection_call(user_message, draft, model)
               │              │
               │              ├─ verdict: "pass" → keep draft
               │              │
               │              └─ verdict: "improve" → improvement_pass(...)
               │                    Agent(instructions=improvement_prompt,
               │                          tools=execution_tools, model)
               │                    Runner.run_sync(agent, ..., max_turns=M)
               │                    → improved_result replaces draft
               │
               └─ Return AgentExecutionResult
                    (text, tools_called, turns_used,
                     reflection_triggered, reflection_improved,
                     plan_text, plan_revisions, routing_method)
          → Log all (vault + DB + etrace)
          → RunResponse
```

**What changes in existing code:**

| File | Change |
|------|--------|
| `orchestrator/runner_execution.py` | Add `should_reflect()` + `run_reflection()` + `run_improvement()` after execution loop; extend `AgentExecutionResult` with `reflection_triggered`, `reflection_improved`. |
| `orchestrator/service.py` | Pass reflection config to `run_agent_execution`; extend `_RunState` and `_AgentResult` with reflection fields; build `## Reflection` section in `_finalize_run`. |
| `config.py` | Add `HARLE_REFLECTION_*` and `HARLE_THINK_TOOL_ENABLED` fields to `Settings`. |
| `tools/think/` (new) | `ThinkToolModule` with the `think` `function_tool`. |
| `tools/factory.py` | Register `ThinkToolModule` when `HARLE_THINK_TOOL_ENABLED` is `True`. |
| `db/models.py` | Add `reflection_triggered` and `reflection_improved` columns to `Run`. |
| `db/runs.py` | Accept and persist new reflection fields in `create_run`. |
| `api/models.py` | Add `reflection_triggered` and `reflection_improved` to `RunResponse`. |

---

#### Cost and latency impact

| Scenario | Extra LLM calls | Extra cost | Extra latency |
|----------|-----------------|------------|---------------|
| Reflection not triggered (simple task) | 0 | $0 | ~0 ms (trigger check is local) |
| Reflection triggered, verdict "pass" | +1 | +$0.002–0.01 | +2–5 sec |
| Reflection triggered, verdict "improve" | +2 | +$0.005–0.02 | +5–15 sec |
| Think tool usage (per call during execution) | 0 (part of execution loop) | ~$0 (no-op) | ~0 ms |

At Harle's usage level (20–50 runs/day), even if 50% of runs trigger reflection, the daily cost increase is <$0.50.

**Estimated complexity:** Low-medium. The reflection trigger is a pure function. The reflection call is a single LLM invocation with structured output parsing. The improvement pass reuses the existing Agent/Runner pattern. The think tool is a trivial `function_tool`. The main work is wiring reflection fields through the logging and API layers.

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
POST /chat → Router.route(request)
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
