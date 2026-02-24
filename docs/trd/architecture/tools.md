---
title: "Harle Tool Module Layer — Architecture & Functionality"
tags: [tools, architecture, registry, modules, skills, extensibility, mcp, openai-agents-sdk]
context: global
last_updated: 2026-02-24
summary: "Describes the Tool Module Layer's internal architecture, the BaseToolModule interface, the Tool Registry, the tool skills system, and how modules connect to the Orchestrator and the OpenAI Agents SDK."
---

# Harle Tool Module Layer — Architecture & Functionality

> The Tool Module Layer is how Harle acts on the outside world. Every time an agent reads Trello cards, searches the web, runs a script, or writes to the vault, the call goes through a tool module. This layer makes capabilities discoverable, configurable, and safe.

This document describes the Tool Module Layer's internal architecture: how tool modules are structured, how the registry discovers and routes tool calls, how tool skills inject domain knowledge into the LLM context, and how the whole layer connects to the Orchestrator and the OpenAI Agents SDK.

For the overall system architecture, see [overview.md](./overview.md).
For the Orchestrator (which consumes tools from this layer), see [orchestrator.md](./orchestrator.md).
For the research behind this design, see [tool_module_architecture.md](../../research/tool_module_architecture.md).

---

## Where the Tool Module Layer Sits

```
                        ┌──────────────────────────────────────────────────┐
                        │              ORCHESTRATOR                        │
                        │                                                  │
                        │  ┌──────────┐   ┌──────────┐   ┌─────────────┐  │
                        │  │ HTTP API │──>│ Router   │──>│ Agent Runner │  │
                        │  └──────────┘   └──────────┘   └──────┬──────┘  │
                        │                                       │         │
                        │                                ┌──────▼──────┐  │
                        │                                │   Tool      │  │
                        │                                │   Module    │  │
                        │                                │   Layer     │  │
                        │                                └──────┬──────┘  │
                        │                                       │         │
                        └───────────────────────────────────────┼─────────┘
                                                                │
                    ┌───────────────────────────────────────────┼────────────┐
                    │                 TOOL MODULE LAYER                      │
                    │                                                       │
                    │  ┌─────────────────────────────────────────────────┐  │
                    │  │              Tool Registry                      │  │
                    │  │                                                 │  │
                    │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐        │  │
                    │  │  │ Trello   │ │   Web    │ │ Scripts  │  ...   │  │
                    │  │  │ Module   │ │ Search   │ │ Module   │        │  │
                    │  │  │          │ │ Module   │ │          │        │  │
                    │  │  │ skills/  │ │ skills/  │ │ skills/  │        │  │
                    │  │  └────┬─────┘ └────┬─────┘ └────┬─────┘        │  │
                    │  └───────┼────────────┼────────────┼──────────────┘  │
                    │          │            │            │                  │
                    │     Trello API    Tavily API    Local scripts        │
                    └──────────────────────────────────────────────────────┘
```

The Tool Module Layer is an internal part of the Orchestrator. It is not a separate service — it runs in the same Python process. It provides three things:

1. **Tool Modules** — self-contained packages of related tools (e.g., all Trello operations live in one module).
2. **Tool Registry** — a central catalog that discovers, registers, and routes tool calls across all modules.
3. **Tool Skills** — optional Markdown files that inject domain knowledge into the LLM context when a module's tools are active.

From the Agent Runner's perspective, the Tool Module Layer is a single interface: "give me the tools this agent needs, with their skills." From a developer's perspective, adding a new integration means creating a new directory with a Python class and optionally some Markdown files — nothing else changes.

---

## Why a Tool Module Layer (Not Just Functions)

An earlier Orchestrator design described tools as individual decorated functions registered in a flat list. This works for a handful of tools but creates problems as the system grows:

| Problem with flat tool functions | How the Tool Module Layer solves it |
|---|---|
| **No grouping.** Trello's `list_cards`, `create_card`, and `move_card` are unrelated functions. | All Trello operations live in `TrelloModule` — one directory, one class, one config block. |
| **No lifecycle.** Where do you initialize the API client? Where do you close connections? | `initialize()` and `shutdown()` are part of the base interface. |
| **No health checks.** If the Trello API key is invalid, you find out when the agent tries to use it. | `health_check()` validates credentials at startup. |
| **No configuration pattern.** Each tool reads env vars or globals differently. | Each module declares its config schema. All config lives in `config.yaml` under `tool_modules`. |
| **No enable/disable.** Removing a tool means editing code. | Each module has an `enabled` flag in config. |
| **No domain knowledge.** The tool function's docstring is all the LLM knows about how to use it. | Tool skills provide rich, contextual guidance in Markdown — when to use the tool, what patterns work best, domain-specific rules. |
| **No security boundary.** A script-execution tool with no constraints can do anything the LLM asks. | Five security layers: permission checks, approval gates, input validation (allowlists, blocklists, path restrictions), execution sandboxing (timeouts, memory limits), and output audit. All configurable per module. |
| **No selective exposure.** All tools are always visible to the LLM. | The registry holds all tools but the Orchestrator selects a subset per request. |

---

## Internal Components

The Tool Module Layer consists of three components. Each has one job.

### 1. BaseToolModule (the contract every module implements)

**What it does:** Defines the interface that every tool module must follow. Any capability you add to Harle — whether it connects to an external API, runs local scripts, or manages vault files — implements this interface.

**Key design principle:** Tool functions are the single source of truth for their names, descriptions, and parameter schemas. The module does not duplicate this information — it only *groups* its tool functions and manages their lifecycle. The registry introspects the functions (docstrings, type hints) to generate the JSON schemas that the LLM sees, exactly as OpenAI's `@function_tool` decorator does.

```python
from abc import ABC, abstractmethod
from typing import Callable


class BaseToolModule(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique module identifier (e.g. 'trello', 'web_search')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable module description for logging and debugging."""
        ...

    @abstractmethod
    async def initialize(self, config: dict) -> None:
        """Set up clients, validate credentials, prepare state."""
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Clean up resources (close HTTP clients, flush buffers)."""
        ...

    @abstractmethod
    def get_tools(self) -> list[Callable]:
        """Return the tool functions this module provides.

        Each function must have type hints and a docstring.
        The registry introspects these to build JSON schemas for the LLM.
        """
        ...

    async def health_check(self) -> bool:
        """Verify the module is operational (e.g. credentials valid)."""
        return True
```

**Skills are not part of the module interface.** Every module has a `skills/` subdirectory by convention (`src/harle/tools/<module>/skills/`). The module class does not need to declare or return this path — the registry knows where to look. Which skill files are actually loaded and injected into the LLM context is controlled by the module's **configuration** in `config.yaml`, not by the module code. This keeps the interface minimal and gives the user full control over which domain knowledge is active without editing Python.

**Where information lives (no duplication):**

| What | Where it lives | Who reads it |
|---|---|---|
| Tool name | Function name (`def search_cards`) | Registry extracts it |
| Tool description | Function docstring | Registry extracts it → LLM sees it |
| Parameter names and types | Function signature + type hints | Registry extracts JSON schema → LLM sees it |
| Domain knowledge | `skills/*.md` files in the module directory | Registry loads files listed in config → Context Assembler injects into LLM prompt |
| Which skills are active | `config.yaml` → `tool_modules.<module>.skills` | Registry reads at startup |
| Module identity | `BaseToolModule.name` | Orchestrator (for config, logging, routing) |
| Module description | `BaseToolModule.description` | Orchestrator (for logging, not sent to LLM) |
| Lifecycle | `initialize()` / `shutdown()` / `health_check()` | Orchestrator |

**Why no manifest file (JSON or YAML):**

Manifest-driven plugin systems (see the research doc, Section 2.3) require a separate file that describes the module's tools, config schema, and capabilities. This duplicates information already present in the Python code. For Harle's scale (5–15 modules, one developer, one repository), the Python class *is* the manifest. The `BaseToolModule` interface provides the same discoverability without the boilerplate.

---

### 2. Tool Registry (discover, register, route)

**What it does:** The Tool Registry is the central catalog of all available tools. It discovers modules, indexes their tool functions, and provides the bridge between the Orchestrator and the OpenAI Agents SDK.

**How the registry works:**

```
Startup:
  Orchestrator reads config.yaml → tool_modules section
  For each enabled module:
    1. Import the module class
    2. Call initialize(config) — sets up API clients, validates credentials
    3. Call health_check() — verifies the module is operational
    4. Call get_tools() — gets the list of tool functions
    5. Index each function by name in the registry
    6. Read config.skills list → load matching .md files from the module's
       skills/ directory and from <vault>/tool_skills/<module>/

Request time:
  Orchestrator asks: "Give me tools for [agent_role] handling [this request]"
  Registry returns:
    1. FunctionTool objects (OpenAI SDK format) for the selected tools
    2. Skill content (Markdown) for the active modules (only files listed in config)
```

**Core interface:**

```python
from agents import FunctionTool


class ToolRegistry:

    def register_module(self, module: BaseToolModule) -> None:
        """Register a module and index its tool functions."""
        self._modules[module.name] = module
        for fn in module.get_tools():
            self._tools[fn.__name__] = (module, fn)

    def get_agent_tools(self, tool_names: list[str]) -> list[FunctionTool]:
        """Convert selected tool functions into OpenAI SDK FunctionTool objects.

        The SDK's FunctionTool introspects each function's signature,
        type hints, and docstring to generate the JSON schema that the
        LLM sees — the same way @function_tool works, without the decorator.
        """
        result = []
        for name in tool_names:
            module, fn = self._tools[name]
            result.append(FunctionTool(fn))
        return result

    def get_skills_for_tools(self, tool_names: list[str]) -> list[str]:
        """Return skill content (Markdown) for the modules that own
        the requested tools. Deduplicated by module."""
        ...

    def list_all_tools(self) -> list[str]:
        """Return names of all registered tools (for logging and debugging)."""
        ...

    async def shutdown_all(self) -> None:
        """Call shutdown() on every registered module."""
        ...
```

**The data flow — single source of truth throughout:**

```
search_cards(board_id: str, status: str) -> str
    """Search Trello cards matching the given status."""
              │
              │  function is the source of truth
              ▼
TrelloModule.get_tools()
    → returns [search_cards, ...]         (just pointers, no metadata)
              │
              ▼
ToolRegistry.get_agent_tools(["search_cards"])
    → FunctionTool(search_cards)          (SDK introspects the function)
              │
              ▼
Agent(tools=[FunctionTool(...)])
    → LLM sees: name="search_cards",
                description="Search Trello cards...",
                parameters={"board_id": {"type": "string"}, ...}
```

No description is written twice. The function defines it once; the SDK reads it.

**Why a registry (not just a list):**

A flat list of functions (`tools = [search_cards, create_card, web_search]`) works until you need:
- **Filtering** — give this agent only Trello tools, not web search.
- **Lifecycle** — shut down all modules cleanly when the server stops.
- **Logging** — know which module a tool belongs to for audit logs.
- **Skills** — load the right domain knowledge for the active tools.

The registry provides all of these while remaining lightweight — under 200 lines of code.

---

### 3. Tool Skills (domain knowledge for tool usage)

**What it does:** Tool skills are Markdown files that provide the LLM with domain knowledge about *how* to use a module's tools effectively. They go beyond the function docstring (which describes *what* the tool does) and teach the LLM *when*, *why*, and *in what patterns* to use the tools.

**The problem skills solve:**

A tool function's docstring is a technical contract: parameter names, types, return values. But the LLM also needs to know things like:

- "When triaging Trello cards, always check the `stalled` status before suggesting reformulations."
- "Web search results should be cross-referenced with the user's dataset before presenting them."
- "Never run scripts with file-deletion commands without explicit user confirmation."
- "When creating Trello cards, always include a due date — the user's convention is 7 days from today for tasks without explicit deadlines."

This kind of knowledge does not belong in function docstrings (too long, changes frequently) and does not belong in the agent's main prompt file (the agent prompt defines the *role*, not tool-specific patterns). Tool skills are the right place: they travel with the module, are written in Markdown (easy to edit), and are injected into the context only when the module's tools are active.

**How skills work:**

```
Module directory (convention — every module has a skills/ subdirectory):
  src/harle/tools/trello/
  ├── module.py          # TrelloModule class
  ├── client.py          # Trello API wrapper
  ├── tools.py           # Tool functions
  └── skills/            # Domain knowledge (Markdown files)
      ├── triage.md      # How to triage stalled tasks
      └── conventions.md # Card naming and labeling conventions

Configuration selects which skills are active:
  # config.yaml
  tool_modules:
    trello:
      enabled: true
      skills: [triage, conventions]    # ← filenames without .md

At request time:
  1. Orchestrator selects tools: [search_cards, create_card]
  2. Registry identifies these belong to "trello" module
  3. Registry returns the pre-loaded skills listed in config (triage.md, conventions.md)
  4. Context Assembler includes skill content in the LLM prompt
     (alongside the agent prompt, policies, and search results)
```

**Why config controls skill selection (not the module class):**

A module may ship with five skill files covering different use cases. A user may only care about two of them — or may have written their own replacements. Listing active skills in `config.yaml` means:
- Adding or removing a skill requires editing a YAML list, not Python code.
- Different deployments can use different skill sets for the same module.
- The module developer ships all available skills; the user decides which are relevant.

**Skill file format:**

Skills are plain Markdown with optional YAML frontmatter. They follow the same conventions as vault files (see [data.md](./data.md)).

```markdown
---
title: "Trello Task Triage — Tool Skill"
tags: [trello, triage, tool-skill]
context: global
last_updated: 2026-02-24
summary: "Guides the LLM on how to triage stalled Trello cards using the Trello module's tools."
---

# Trello Task Triage

When asked to find or triage stalled tasks, follow this pattern:

1. Call `search_cards` with `status="stalled"` to get the full list.
2. Group results by list (To Do, In Progress, Blocked).
3. For each stalled card, check the `last_activity` field.
   - Cards stalled for 7–14 days: suggest a reformulation.
   - Cards stalled for 14+ days: suggest archiving or escalation.
4. When suggesting reformulations, break vague titles into
   specific, actionable tasks with clear completion criteria.

## Card Naming Conventions

- Start with a verb: "Draft ...", "Review ...", "Implement ..."
- Include scope: "Draft /run endpoint schema" not "Draft schema"
- Keep titles under 80 characters
```

**Where skills can come from (two sources):**

Skills can be bundled with the module *and* extended from the user's vault. This dual-source model means developers ship sensible defaults while users customize behavior without editing application code.

| Source | Location | Who writes it | When it changes |
|---|---|---|---|
| **Built-in skills** | `src/harle/tools/<module>/skills/` (inside the code repository) | Developer | When the module is created or updated. Shipped with the application. |
| **User skills** | `<vault>/tool_skills/<module>/` (inside the user's vault) | User | Anytime. Customizes or extends built-in skills without code changes. |

**Loading order and precedence:**

```
For each skill name listed in config.skills (e.g. "triage"):
  1. Check <vault>/tool_skills/<module>/triage.md — if it exists, use it
  2. Otherwise, load src/harle/tools/<module>/skills/triage.md
  3. If neither exists, log a warning and skip

All loaded skills are concatenated and included in the context.
```

This means:
- A fresh Harle installation works out of the box — built-in skills provide reasonable defaults for all names listed in config.
- A user can override any built-in skill by creating a file with the same name in their vault's `tool_skills/<module>/` directory.
- A user can add entirely new skills that do not exist in the codebase (e.g., `company_rules.md`) — they just add the filename to the config's `skills` list and place the file in their vault.
- Removing a skill from the active set means deleting its name from the `skills` list in config — no file deletion needed.

**Token budget for skills:**

Skills consume context window tokens. The Context Assembler (see [orchestrator.md](./orchestrator.md)) manages this:

- Skills are loaded at **priority P1** (same as direct search results from the dataset).
- If multiple modules are active and their combined skills exceed the token budget, skills are trimmed by relevance — skills from the primary module (the one whose tools are most likely to be called) are kept; secondary module skills are summarized or dropped.
- Each skill file should be concise: **1–3 pages maximum**. This is enforced by convention, not by code.

**Why Markdown (not code, not JSON, not YAML):**

- **Editable by non-developers.** A project manager or domain expert can write a skill without knowing Python.
- **Consistent with the vault.** Harle's knowledge base is Markdown. Skills follow the same format, tooling, and conventions.
- **Readable by the LLM.** Markdown is the format LLMs understand best — headings provide structure, lists provide clarity, code blocks provide precision.
- **Version-controlled.** Both built-in skills (in the code repo) and user skills (in the vault) are tracked by Git.

---

## Tool Module Structure

Every tool module follows the same directory layout:

```
src/harle/tools/
├── __init__.py
├── registry.py                # ToolRegistry class
├── base.py                    # BaseToolModule ABC
│
├── trello/
│   ├── __init__.py
│   ├── module.py              # TrelloModule(BaseToolModule)
│   ├── client.py              # Trello API wrapper (httpx)
│   ├── tools.py               # search_cards, create_card, move_card, ...
│   └── skills/
│       ├── triage.md          # How to triage stalled tasks
│       └── conventions.md     # Card naming, labeling rules
│
├── web_search/
│   ├── __init__.py
│   ├── module.py              # WebSearchModule(BaseToolModule)
│   ├── client.py              # Tavily / SearXNG wrapper
│   ├── tools.py               # search_web, search_news, fetch_page, ...
│   └── skills/
│       └── research.md        # How to structure search queries, cross-reference results
│
├── scripts/
│   ├── __init__.py
│   ├── module.py              # ScriptsModule(BaseToolModule)
│   ├── tools.py               # run_script, list_scripts, ...
│   └── skills/
│       └── safety.md          # Script execution safety rules
│
├── vault/
│   ├── __init__.py
│   ├── module.py              # VaultModule(BaseToolModule)
│   ├── tools.py               # read_note, create_note, update_note, search_notes, ...
│   └── skills/
│       └── conventions.md     # File naming, frontmatter rules, directory layout
│
├── notion/
│   └── ...
│
└── twitter/
    └── ...
```

**User vault extension point:**

```
~/harle-vault/
├── prompts/                   # Agent role definitions (existing)
├── policies/                  # Rules and constraints (existing)
├── workflows/                 # Task templates (existing)
├── knowledge/                 # Knowledge base (existing)
│
└── tool_skills/               # ← NEW: user-defined tool skills
    ├── trello/
    │   └── company_rules.md   # Company-specific Trello conventions
    ├── web_search/
    │   └── sources.md         # Preferred sources, sites to avoid
    └── scripts/
        └── approved.md        # List of pre-approved script patterns
```

---

## Example: Trello Module (Complete)

This section shows a complete tool module to illustrate how all the pieces fit together.

**`src/harle/tools/trello/tools.py`** — the tool functions (single source of truth):

```python
async def search_cards(board_id: str, status: str = "all") -> str:
    """Search Trello cards on a board, optionally filtered by status.

    Args:
        board_id: The Trello board ID to search in.
        status: Filter by card status. Options: all, active, stalled, done.
                'stalled' means no activity for 14+ days.

    Returns:
        JSON string with matching cards (id, title, list, labels, last_activity).
    """
    ...


async def create_card(
    board_id: str, list_name: str, title: str, due_date: str | None = None
) -> str:
    """Create a new Trello card in the specified list.

    Args:
        board_id: The Trello board ID.
        list_name: Name of the list to add the card to (e.g. 'To Do').
        title: Title for the new card.
        due_date: Optional due date in ISO 8601 format (YYYY-MM-DD).

    Returns:
        JSON string with the created card's id and URL.
    """
    ...


async def move_card(card_id: str, target_list: str) -> str:
    """Move a Trello card to a different list.

    Args:
        card_id: The Trello card ID.
        target_list: Name of the destination list (e.g. 'Done').

    Returns:
        Confirmation message with the card title and new list.
    """
    ...
```

**`src/harle/tools/trello/module.py`** — the module class:

```python
from harle.tools.base import BaseToolModule
from harle.tools.trello.tools import search_cards, create_card, move_card
from harle.tools.trello.client import TrelloClient


class TrelloModule(BaseToolModule):
    name = "trello"
    description = "Trello board management for task tracking"

    async def initialize(self, config: dict) -> None:
        self._client = TrelloClient(
            api_key=config["api_key"],
            api_token=config["api_token"],
        )
        self._default_board = config.get("default_board")

    async def shutdown(self) -> None:
        await self._client.close()

    def get_tools(self) -> list:
        return [search_cards, create_card, move_card]
        # Skills are in src/harle/tools/trello/skills/ by convention.
        # Which skills are active is controlled by config.yaml.

    async def health_check(self) -> bool:
        return await self._client.verify_credentials()
```

**`src/harle/tools/trello/skills/triage.md`** — a built-in skill:

```markdown
# Trello Task Triage

When triaging Trello tasks, follow this sequence:

1. Call `search_cards` with `status="stalled"` to find all inactive cards.
2. Group results by list (To Do, In Progress, Blocked).
3. For cards stalled 7–14 days: suggest a title reformulation
   that makes the task more specific and actionable.
4. For cards stalled 14+ days: recommend archiving, delegating,
   or breaking into smaller tasks.
5. Present results as a numbered list with the original title,
   days stalled, and your suggestion.

Always prefer reformulations that start with a verb and include
a clear scope (e.g., "Draft the /run endpoint schema" instead of
"Work on API").
```

---

## How It Works End-to-End

### Startup

```
1. Orchestrator reads config.yaml → tool_modules section
2. For each enabled module:
   a. Import module class (e.g. TrelloModule from src/harle/tools/trello/)
   b. Call module.initialize(config) → sets up API clients, validates credentials
   c. Call module.health_check() → verifies the module is operational
      - If health check fails: log a warning, mark module as degraded,
        continue with other modules
   d. Call registry.register_module(module) → indexes all tool functions
   e. Read config.skills list for this module (e.g. [triage, conventions])
   f. For each skill name: load from <vault>/tool_skills/<module>/ first,
      fall back to src/harle/tools/<module>/skills/
   g. Cache loaded skill content in the registry, keyed by module name
3. Log: "Tool Module Layer ready: 4 modules, 11 tools, 7 skills"
```

### Request Processing

```
1. Orchestrator receives a user request
2. Router determines the agent role (secretary, researcher, specialist)
3. Orchestrator determines which tools this agent needs:
   - From the agent's prompt file (tools-allowlist)
   - From the request content (mentions Trello → include trello tools)
   - Subject to the "keep tool count low" rule (5–15 tools per request)
4. Orchestrator calls registry.get_agent_tools(tool_names)
   → returns FunctionTool objects for the OpenAI Agents SDK
5. Orchestrator calls registry.get_skills_for_tools(tool_names)
   → returns skill Markdown content for the active modules
6. Context Assembler includes skill content in the prompt
   (at priority P1, alongside dataset search results)
7. Agent Runner executes with the tools and enriched context
8. When the LLM calls a tool, the SDK invokes the original function
9. Tool results flow back through the agentic loop
```

### Shutdown

```
1. Orchestrator calls registry.shutdown_all()
2. Registry iterates over all registered modules
3. Each module's shutdown() is called → closes HTTP clients, flushes buffers
4. Log: "Tool Module Layer shut down cleanly"
```

---

## Tool Permissions and Approval Flow

Tool modules integrate with the Orchestrator's approval system. Each tool function carries permission metadata that the registry enforces.

**Permission model:**

| Permission | What it means | Approval needed? |
|---|---|---|
| `read` | The tool only reads data. No side effects. | No |
| `write` | The tool creates or modifies data. | Yes (configurable) |
| `delete` | The tool removes data. | Always |

**How permissions are declared:**

Permissions are declared as function attributes rather than in the module class, keeping the single-source-of-truth principle:

```python
async def search_cards(board_id: str, status: str = "all") -> str:
    """Search Trello cards on a board."""
    ...

search_cards.permission = "read"
search_cards.requires_approval = False


async def create_card(board_id: str, list_name: str, title: str) -> str:
    """Create a new Trello card."""
    ...

create_card.permission = "write"
create_card.requires_approval = True
```

**Approval flow:**

```
Agent decides to call create_card(...)
         │
         ▼
Registry checks: requires_approval = True
         │
         ▼
Module's operation mode (from config):
  ├── read_only   → Block the call. Agent is told the tool is read-only.
  ├── propose     → Pause. Show the proposed action to the user for approval.
  └── auto        → Execute without approval (only for low-risk write actions).
         │
    (if propose mode)
         ▼
User sees:
  "Agent wants to create a Trello card:
   Board: Work │ List: To Do
   Title: Draft the /run endpoint schema
   Approve? [y/n]"
         │
    ┌────┴────┐
   [y]       [n]
    │         │
    ▼         ▼
  Execute   Skip, agent
  the tool  continues without it
```

**Operation modes per module:**

Each module can be configured with an operation mode that controls the default approval behavior:

| Mode | Behavior | Best for |
|---|---|---|
| `read_only` | Only read tools are callable. Write/delete tools are blocked. | Initial setup, cautious deployment |
| `propose` | Write/delete tools pause for user approval. Read tools execute freely. | Day-to-day usage (default) |
| `auto` | All tools execute without approval. | Scripted/automated workflows (`harle exec --yes`) |

---

## Tool Security

The permission model above (read/write/delete + approval flow) answers the question "should this tool be called?" But it does not answer "what is this tool *allowed to do* once called?" For API-based tools like Trello, the damage is bounded — the worst case is a misplaced card. For tools that interact with the local system — script execution, file operations, shell commands — the damage is unbounded unless the tool itself enforces constraints.

This section defines the security mechanisms that prevent tools from causing harm, even when the LLM produces unexpected inputs or a module is misconfigured.

### The Threat Model

Harle runs on the user's own machine or server. The LLM is an external service that generates tool calls based on prompts. The threats are:

| Threat | Example | How likely |
|---|---|---|
| **LLM produces a destructive command** | The LLM calls `run_script` with `rm -rf /` as the command. | Low but non-zero — prompt injection, model confusion, or adversarial input can trigger it. |
| **LLM exfiltrates data via a tool** | The LLM calls `web_search` or `fetch_page` with a URL containing private data as query parameters. | Low — requires prompt injection or a deliberately crafted request. |
| **LLM exhausts resources** | The LLM calls a script that runs an infinite loop or writes terabytes to disk. | Medium — easy for the LLM to produce, hard for it to predict consequences. |
| **LLM chains tools to escalate** | The LLM reads a credential file via the vault tool, then uses it in a web request. | Low — requires multi-step reasoning with malicious intent, unlikely from current models without prompt injection. |
| **Misconfigured module** | A developer sets `mode: auto` on the scripts module with no other constraints. | Medium — human error during configuration. |

The security model follows the principle of **defense in depth**: no single mechanism prevents all threats. Instead, multiple layers work together so that a failure in one layer does not lead to harm.

### Security Layers

```
LLM generates a tool call
         │
    Layer 1: PERMISSION CHECK
         │  Does the agent's role allow this tool? (tools-allowlist in vault)
         │  Is the module's mode compatible? (read_only blocks writes)
         │
    Layer 2: APPROVAL GATE
         │  Does this tool require approval? (propose mode)
         │  User sees the full call and decides [y/n]
         │
    Layer 3: INPUT VALIDATION
         │  Does the input match the tool's constraints?
         │  (allowlists, blocklists, path restrictions, regex filters)
         │
    Layer 4: EXECUTION SANDBOX
         │  Resource limits: timeout, memory cap, disk quota
         │  Filesystem restrictions: chroot or allowed paths
         │  Network restrictions: allowed destinations
         │
    Layer 5: OUTPUT AUDIT
         │  Log the full call: tool name, inputs, outputs, duration
         │  Flag anomalies for review
         │
         ▼
    Result returned to the LLM
```

### Layer 3: Input Validation (per-tool constraints)

Each tool can declare **constraints** that are checked *before* execution — after approval but before the function body runs. Constraints are enforced by the registry, not by the tool function itself, so they cannot be bypassed by a bug in the tool code.

**Constraint types:**

| Constraint | What it does | Example |
|---|---|---|
| **`allowed_commands`** | Allowlist of command names or patterns that the tool may execute. Anything not on the list is rejected. | `["python", "bash", "node"]` — prevents `rm`, `curl`, `sudo` |
| **`blocked_patterns`** | Regex patterns that are rejected if found anywhere in the input arguments. | `["rm\\s+-rf", "sudo\\s+", "> /dev/", "\\|\\s*sh"]` |
| **`allowed_paths`** | Filesystem paths the tool may access. Paths outside this list are rejected. Symlink resolution prevents escapes. | `["${HARLE_VAULT_PATH}", "/tmp/harle"]` |
| **`blocked_paths`** | Paths the tool must never access, even if they are within `allowed_paths`. | `["/etc/", "~/.ssh/", "~/.config/harle/config.yaml"]` |
| **`allowed_hosts`** | For network-accessing tools: domains the tool may contact. | `["api.trello.com", "api.tavily.com"]` |
| **`max_input_length`** | Maximum character length for any single argument. Prevents prompt-stuffing. | `10000` |

**How constraints are declared (in config, not in code):**

Constraints are part of the module's configuration in `config.yaml`, not hardcoded in the Python tool function. This means users can tighten or adjust constraints for their deployment without editing code.

```yaml
tool_modules:
  scripts:
    enabled: true
    mode: propose
    skills: [safety]
    scripts_dir: "${HARLE_VAULT_PATH}/scripts"
    timeout_seconds: 30

    # Security constraints
    constraints:
      allowed_commands: ["python", "python3", "bash", "node"]
      blocked_patterns:
        - "rm\\s+-rf"
        - "sudo\\s+"
        - "chmod\\s+777"
        - ">(\\s+)/dev/"
        - "\\|\\s*(bash|sh|zsh)"
        - "curl.*\\|.*sh"
      allowed_paths:
        - "${HARLE_VAULT_PATH}"
        - "/tmp/harle"
      blocked_paths:
        - "/etc/"
        - "~/.ssh/"
        - "~/.gnupg/"
        - "~/.config/"

  vault:
    enabled: true
    mode: propose
    skills: [conventions]
    constraints:
      allowed_paths:
        - "${HARLE_VAULT_PATH}"
      blocked_paths:
        - "${HARLE_VAULT_PATH}/.git"   # Prevent direct git manipulation
```

**Why config, not code:** A developer might forget a pattern. A user deploying Harle in a corporate environment might need stricter rules. Keeping constraints in config means security policy is visible, auditable, and adjustable without a code release.

**Default constraints:** Modules that interact with the local system (scripts, vault) ship with **recommended default constraints** documented in `config.example.yaml`. If a module's config section has no `constraints` key, the module is still subject to Layer 1 (permission) and Layer 2 (approval) — but has no input-level restrictions. The `config.example.yaml` template includes all recommended constraints so that a fresh deployment starts secure.

### Layer 4: Execution Sandbox (resource limits)

Even a well-intentioned command can cause harm if it runs too long, uses too much memory, or writes too much data. Resource limits ensure that a tool call is bounded, regardless of what it does.

**Resource limits (per tool call):**

| Limit | What it prevents | Default | Configurable? |
|---|---|---|---|
| **Timeout** | Infinite loops, hung processes, slow APIs | 30 seconds | Yes, per module (`timeout_seconds`) |
| **Memory** | Memory bombs (`python -c "x='a'*10**12"`) | 512 MB per tool call | Yes, per module (`max_memory_mb`) |
| **Output size** | Writing gigabytes to stdout or a file | 1 MB of captured output | Yes, per module (`max_output_bytes`) |
| **Disk write** | Filling the disk | Restricted to `allowed_paths`; no size limit beyond disk quota | Via `allowed_paths` |
| **Network** | Exfiltration, contacting unintended hosts | Restricted to `allowed_hosts` (if declared) | Yes, per module |
| **Subprocess count** | Fork bombs | 10 child processes | Yes, per module (`max_subprocesses`) |

**How resource limits are enforced:**

For tools that execute external processes (scripts module, future shell module), limits are enforced at the OS level:

```
Tool call: run_script("analyze_data.py")
         │
         ▼
    Registry runs input validation (Layer 3)
         │  ✓ "python" is in allowed_commands
         │  ✓ No blocked patterns found
         │  ✓ Script path is within allowed_paths
         │
         ▼
    Registry spawns the process with limits:
         │  - subprocess.run() with timeout=30
         │  - ulimit or resource module for memory cap
         │  - Output captured with size limit
         │  - Working directory set to allowed path
         │
         ▼
    If timeout/memory exceeded → process killed, error returned to LLM
    If output too large → truncated, warning returned to LLM
    If completes normally → output returned to LLM
```

For tools that call external APIs (Trello, web search), resource limits are simpler — `httpx` timeout settings and response size limits handle most cases.

### Layer 5: Output Audit

Every tool call is logged by the Run Logger (see [orchestrator.md](./orchestrator.md), Section 7) with full details:

```json
{
  "tool": "run_script",
  "module": "scripts",
  "input": {"script": "analyze_data.py", "args": ["--format=csv"]},
  "constraints_checked": {
    "allowed_commands": "pass",
    "blocked_patterns": "pass",
    "allowed_paths": "pass"
  },
  "approval": "user_approved",
  "output_summary": "CSV output, 142 lines",
  "duration_ms": 1200,
  "resource_usage": {"memory_mb": 45, "output_bytes": 8320}
}
```

This audit trail serves two purposes:
1. **After-the-fact review.** If something goes wrong, you can trace exactly what was executed, what inputs were provided, and what constraints were checked.
2. **Pattern detection.** The Specialist agent can analyze tool call logs to flag unusual patterns — e.g., repeated failed constraint checks might indicate a prompt injection attempt.

### Sensitive Tools: The Scripts Module as a Case Study

The scripts module is the most dangerous tool in Harle because it executes arbitrary code on the host system. Here is how all five security layers work together to make it safe:

```
User: "Run the data analysis script"
         │
    Layer 1: PERMISSION
         │  Secretary role's tools-allowlist includes "run_script" → ✓
         │
    Layer 2: APPROVAL
         │  Module mode is "propose" → user sees:
         │  "Agent wants to run: python analyze_data.py --format=csv"
         │  Approve? [y/n] → user approves
         │
    Layer 3: INPUT VALIDATION
         │  "python" is in allowed_commands → ✓
         │  No blocked patterns in arguments → ✓
         │  Script path resolves to /home/user/harle-vault/scripts/analyze_data.py
         │    → within allowed_paths → ✓
         │    → not in blocked_paths → ✓
         │    → symlink check: real path still within allowed_paths → ✓
         │
    Layer 4: EXECUTION SANDBOX
         │  Process spawned with:
         │    timeout=30s, memory_limit=512MB, max_output=1MB
         │    working_directory=/home/user/harle-vault/scripts/
         │    no network access (allowed_hosts is empty for scripts)
         │
    Layer 5: OUTPUT AUDIT
         │  Full call logged: command, args, duration, memory, output size
         │  No anomalies detected
         │
         ▼
    Result returned to LLM: "Analysis complete. 142 records processed..."
```

If *any* layer fails, execution stops and the LLM receives an error explaining what was blocked and why. The agent can then inform the user or try a different approach.

### Security Summary

| Principle | How it is implemented |
|---|---|
| **Least privilege** | Each module's config defines the minimum access it needs (`allowed_paths`, `allowed_commands`, `allowed_hosts`). Nothing is allowed by default. |
| **Defense in depth** | Five layers, each independently effective. A failure in one does not compromise the system. |
| **Fail closed** | If a constraint check errors out (e.g., regex parsing fails), the tool call is blocked, not allowed. |
| **Visible policy** | All constraints are in `config.yaml` — auditable, diffable, reviewable. Not buried in code. |
| **User retains control** | Approval gates (`propose` mode) let the user inspect every dangerous call before it runs. |
| **Auditable** | Every tool call is logged with full inputs, constraint results, and outputs. |

---

## MCP Compatibility

The Tool Module Layer is designed with MCP (Model Context Protocol) in mind, but MCP is an **export layer**, not the primary internal interface.

```
                    ┌─────────────────────┐
                    │    Tool Registry     │
                    │                      │
    Internal:       │  ┌──────────────┐   │      Export (optional):
    BaseToolModule ─┤  │ Trello       │   │──── MCP Server wrapper
                    │  │ Module       │   │     (for Cursor, Claude, etc.)
                    │  └──────────────┘   │
                    │  ┌──────────────┐   │
    BaseToolModule ─┤  │ Vault        │   │
                    │  │ Module       │   │
                    │  └──────────────┘   │
                    │  ┌──────────────┐   │
    MCP Provider ───┤  │ GitHub (ext) │   │      Import:
                    │  │ via MCP      │   │      Consuming existing
                    │  └──────────────┘   │      MCP servers
                    └─────────────────────┘
```

**Three MCP interaction modes:**

| Mode | Direction | What it does | When to use |
|---|---|---|---|
| **Internal** | None (in-process) | Modules communicate with the Orchestrator through `BaseToolModule`. Fast, simple, no protocol overhead. | Default for all Harle-owned modules |
| **Export** | Harle → External | A thin wrapper exposes any module as an MCP server. Other tools (Cursor, Claude) can call Harle's tools. | When you want Harle's tools available in other AI clients |
| **Import** | External → Harle | The registry consumes external MCP servers (e.g., a community-built GitHub MCP server) through an `McpToolProvider` adapter. | When a pre-built MCP server already exists and works well |

**Why internal-first (not MCP-first):**

- **No process overhead.** In-process function calls are nanoseconds. MCP calls cross process boundaries (~1–5ms for stdio, more for HTTP).
- **Simpler debugging.** Stack traces stay in one process. Errors do not cross protocol boundaries.
- **No schema explosion.** With MCP, each server's full tool list is sent to the LLM. With internal modules, the registry selects exactly which tools to expose — keeping token usage low.
- **MCP is additive.** Any internal module can be wrapped as an MCP server later without changing the module's code.

---

## Configuration

Tool module configuration lives in the Orchestrator's `config.yaml` under the `tool_modules` key. Each module has its own section.

```yaml
tool_modules:
  trello:
    enabled: true
    api_key: ${TRELLO_API_KEY}
    api_token: ${TRELLO_API_TOKEN}
    default_board: "Work Tasks"
    mode: propose                    # read_only | propose | auto
    skills: [triage, conventions]    # .md filenames from skills/ dir

  web_search:
    enabled: true
    provider: tavily                 # tavily | bing | searxng
    api_key: ${TAVILY_API_KEY}
    max_results: 5
    mode: auto                       # search is read-only, auto is safe
    skills: [research]

  scripts:
    enabled: true
    scripts_dir: "${HARLE_VAULT_PATH}/scripts"
    allowed_extensions: [".py", ".sh"]
    timeout_seconds: 30
    mode: propose                    # script execution always needs approval
    skills: [safety]

  vault:
    enabled: true
    vault_path: ${HARLE_VAULT_PATH}
    mode: propose
    skills: [conventions]

  notion:
    enabled: false
    api_key: ${NOTION_API_KEY}
    skills: []                       # No skills active (module disabled anyway)

  twitter:
    enabled: false
    skills: []

# Global skill loading settings
tool_skills:
  user_skills_dir: "${HARLE_VAULT_PATH}/tool_skills"
  max_tokens_per_module: 2000       # Token budget for skills per module
```

**Configuration sources (priority order):**

| Priority | Source | Example |
|---|---|---|
| **1 (highest)** | Environment variables | `TRELLO_API_KEY=abc123` |
| **2** | `config.yaml` values | `api_key: ${TRELLO_API_KEY}` |
| **3 (lowest)** | Module defaults (in code) | `mode: "propose"` |

**Key conventions:**
- Secrets (API keys, tokens) are always referenced via environment variables (`${VAR_NAME}`), never hardcoded.
- The `enabled` flag lets you toggle modules without removing their config.
- The `mode` flag controls the approval behavior per module — independent of the global approval setting.
- The `skills` list controls which `.md` files from the module's `skills/` directory (or the user's `tool_skills/<module>/` override directory) are loaded and provided to the LLM. Filenames are listed without the `.md` extension. An empty list means no skills are active for that module.

---

## Error Handling

Errors in the Tool Module Layer are caught and reported without crashing the Orchestrator or the agent. Each error type has a defined recovery path:

| Error | What happens | User experience |
|---|---|---|
| **Module init fails** | Module is marked as unavailable. Other modules continue. Warning logged. | "Trello module is unavailable (invalid API key). Other tools are working." |
| **Health check fails** | Same as init failure — module marked degraded. Periodic re-check. | Agent skips tools from that module. Warning in run log. |
| **Constraint violation** | Tool call is blocked before execution. The LLM receives an error naming the violated constraint. | "Blocked: command 'sudo apt install ...' is not in the allowed_commands list for the scripts module." |
| **Blocked pattern matched** | Tool call is blocked. The matching pattern is named in the error. | "Blocked: input contains a disallowed pattern ('rm -rf'). This command is not permitted." |
| **Path outside allowed scope** | Tool call is blocked. The resolved path and allowed scope are reported. | "Blocked: path '/etc/passwd' is outside the allowed paths for the vault module." |
| **Resource limit exceeded** | Process is killed. Partial output (if any) is returned with a warning. | "Script exceeded the 512 MB memory limit and was terminated." |
| **Tool call fails** | Error message returned to the LLM as the tool result. The LLM can try a different approach or report the issue. | "Could not read Trello cards (HTTP 401). Check your API key." |
| **Tool call timeout** | Call is cancelled after the configured timeout. Error returned to LLM. | "Trello API did not respond within 30 seconds." |
| **Skill file not found** | Skipped silently. Other skills load normally. | None visible — the skill is simply not in the context. |
| **Skill file too large** | Truncated to the configured token limit with a `[truncated]` marker. | The LLM sees a partial skill. The full version is in the file. |
| **Module not found in config** | Module directory exists but has no config entry → module is not loaded. | Module is invisible. No error unless explicitly requested. |
| **Naming conflict** | Two modules register tools with the same function name → the second registration raises an error at startup. | Startup fails fast with a clear message: "Tool name 'search' is already registered by module 'web_search'. Rename the function in module 'vault'." |

All errors are included in the Run Logger's output (see [orchestrator.md](./orchestrator.md), Section 7) with the module name, tool name, error type, and full details for debugging.

---

## Project Structure

```
src/harle/tools/                       ← Tool Module Layer code
├── __init__.py
├── base.py                            # BaseToolModule ABC
├── registry.py                        # ToolRegistry class
├── skills.py                          # Skill loader (reads .md files, handles overrides)
├── permissions.py                     # Permission checking, approval flow integration
│
├── trello/                            # Trello module
│   ├── __init__.py
│   ├── module.py                      # TrelloModule(BaseToolModule)
│   ├── client.py                      # Trello API wrapper (httpx)
│   ├── tools.py                       # search_cards, create_card, move_card
│   └── skills/                        # Built-in skills
│       ├── triage.md
│       └── conventions.md
│
├── web_search/                        # Web Search module
│   ├── __init__.py
│   ├── module.py                      # WebSearchModule(BaseToolModule)
│   ├── client.py                      # Tavily / Bing / SearXNG wrapper
│   ├── tools.py                       # search_web, search_news, fetch_page
│   └── skills/
│       └── research.md
│
├── scripts/                           # Script execution module
│   ├── __init__.py
│   ├── module.py                      # ScriptsModule(BaseToolModule)
│   ├── tools.py                       # run_script, list_scripts
│   └── skills/
│       └── safety.md
│
├── vault/                             # Vault (dataset) operations module
│   ├── __init__.py
│   ├── module.py                      # VaultModule(BaseToolModule)
│   ├── tools.py                       # read_note, create_note, update_note, search_notes
│   └── skills/
│       └── conventions.md
│
├── notion/                            # (future)
│   └── ...
│
└── twitter/                           # (future)
    └── ...
```

**Key dependencies (in addition to the Orchestrator's):**

| Package | Purpose |
|---|---|
| `openai-agents` | `FunctionTool` class for converting functions to SDK-compatible tools |
| `httpx` | Async HTTP client for external API calls (Trello, Tavily, Notion) |
| `pyyaml` | Parsing skill file frontmatter |
| `tiktoken` | Token counting for skill budget management |

---

## Technology Choices Summary

| Decision | Choice | Key reason |
|---|---|---|
| **Module interface** | Python ABC (`BaseToolModule`) | Type-safe, IDE-discoverable, no external schema files |
| **Tool definition** | Plain Python functions with type hints and docstrings | Single source of truth — no schema duplication |
| **Registry pattern** | Central `ToolRegistry` class | Aggregation, filtering, lifecycle management, skill loading |
| **SDK bridge** | OpenAI Agents SDK `FunctionTool` | Direct function introspection, no manual schema writing |
| **Skill format** | Markdown files | Editable by non-developers, readable by LLMs, version-controlled |
| **Skill override** | User vault `tool_skills/<module>/` | Customization without code changes |
| **Internal protocol** | In-process Python calls | Fast, simple, debuggable |
| **External protocol** | MCP (optional export/import layer) | Interoperability with Cursor, Claude, community MCP servers |
| **API client** | httpx (async) | Non-blocking, modern, consistent across modules |
| **Permission model** | Function attributes (`fn.permission`, `fn.requires_approval`) | Metadata stays with the function, not in a separate config |
| **Configuration** | `config.yaml` under `tool_modules` key | Centralized, per-module, supports env var substitution |

---

## Incremental Implementation Plan

The Tool Module Layer is built in eight phases. Each phase produces a working, testable result — the system is usable after any phase, and later phases add capabilities without breaking what came before. No big-bang migration is required.

### Phase overview

```
Phase 1: Core infrastructure (base.py, registry.py)
    │
    ├──→ Phase 2: First module — Web Search (proof of concept)
    │       │
    │       └──→ Phase 5: Orchestrator wiring (registry replaces direct tool refs)
    │               │
    │               ├──→ Phase 6: Additional modules (Trello, vault, scripts)
    │               │
    │               └──→ Phase 8: MCP compatibility (optional export/import)
    │
    ├──→ Phase 3: Security layer (constraints, sandbox, audit)
    │       │
    │       └──→ Phase 6: Additional modules (scripts module requires Phase 3)
    │
    └──→ Phase 4: Skills system (loader, config-driven selection, vault overrides)
            │
            └──→ Phase 6: Additional modules (ship with skills)
```

Phases 2, 3, and 4 can be developed in parallel after Phase 1 — they are independent of each other. Phase 5 requires Phase 2. Phase 6 requires Phases 3, 4, and 5. Phase 7 and 8 can be done at any point after Phase 5.

---

### Phase 1: Core Infrastructure

**Goal:** Establish the module contract and the central registry. After this phase, the pattern exists and can accept modules — but no real tools are registered yet.

**What is built:**

| File | Contents |
|---|---|
| `src/harle/tools/__init__.py` | Package init, re-exports `BaseToolModule` and `ToolRegistry` |
| `src/harle/tools/base.py` | `BaseToolModule` ABC — `name`, `description`, `initialize()`, `shutdown()`, `get_tools()`, `health_check()` |
| `src/harle/tools/registry.py` | `ToolRegistry` — `register_module()`, `get_agent_tools()`, `list_all_tools()`, `shutdown_all()` |
| `src/harle/tools/permissions.py` | Permission checking logic — reads `fn.permission` and `fn.requires_approval` attributes, checks against module mode |

**Verification:** Write a test module with a dummy tool function. Register it with the registry. Call `get_agent_tools()` and verify it returns a valid `FunctionTool` object that the OpenAI Agents SDK accepts.

**Dependencies:** None. This is the starting point.

**Estimated size:** ~300 lines of production code, ~200 lines of tests.

---

### Phase 2: First Module — Web Search

**Goal:** Prove the pattern works end-to-end with a real integration. Web Search is the first module because it is needed by nearly every agent role (Researcher, Secretary, Specialist), has a simple API surface (send a query, get results), is read-only (no risk of modifying external data), and delivers immediate visible value — the agent can answer questions using live information.

**Why Web Search first (not Trello):**
- **Broader utility.** Every agent role benefits from web search. Trello is primarily useful for the Secretary. Starting with the most widely used module means the pattern is validated against the most common request path.
- **Read-only.** Web search has no write operations, so approval flow and operation modes are not exercised yet — keeping the proof-of-concept focused on the core pattern (module → registry → FunctionTool → LLM).
- **Simple contract.** The Tavily API takes a query string and returns structured results. No complex state management (boards, lists, cards), no multi-entity relationships.

**What is built:**

| File | Contents |
|---|---|
| `src/harle/tools/web_search/__init__.py` | Package init |
| `src/harle/tools/web_search/module.py` | `WebSearchModule(BaseToolModule)` — lifecycle, tool list, provider selection (Tavily/Bing/SearXNG) |
| `src/harle/tools/web_search/client.py` | Search API wrapper using httpx — abstraction over Tavily, Bing, and SearXNG with a common response format |
| `src/harle/tools/web_search/tools.py` | Tool functions: `search_web`, `search_news`, `fetch_page` |

**What is NOT built yet:** Skills (Phase 4), security constraints (Phase 3), Orchestrator wiring (Phase 5). The module can be tested in isolation — import it, call `initialize()`, call tool functions directly.

**Verification:**
- Unit tests with mocked Tavily API responses.
- Manual integration test: register `WebSearchModule` with the registry, call `get_agent_tools(["search_web"])`, verify the returned `FunctionTool` produces correct JSON schema from the function's docstring and type hints.
- Verify provider abstraction: swap `provider: tavily` to `provider: bing` in config and confirm the module initializes correctly with a different client.

**Dependencies:** Phase 1 (base, registry).

**Estimated size:** ~350 lines of production code (client + tools + module), ~250 lines of tests.

---

### Phase 3: Security Layer

**Goal:** Build the input validation and execution sandbox infrastructure so that modules with local system access (scripts, vault) can be added safely.

**What is built:**

| File | Contents |
|---|---|
| `src/harle/tools/constraints.py` | Constraint engine — loads constraint config, validates tool inputs against `allowed_commands`, `blocked_patterns`, `allowed_paths`, `blocked_paths`, `allowed_hosts`, `max_input_length` |
| `src/harle/tools/sandbox.py` | Execution sandbox — wraps `subprocess.run()` with timeout, memory limits, output size cap, working directory restriction, subprocess count limit |
| Updates to `registry.py` | Registry calls constraint engine before executing any tool. If validation fails, error is returned to the LLM without executing the function. |

**Constraint enforcement flow (added to registry):**

```
registry.execute_tool(name, params)
    │
    ├── Load constraints from config for this tool's module
    ├── Run constraint checks (allowed_commands, blocked_patterns, paths, hosts)
    │     └── If any check fails → return error, do not execute
    ├── If tool spawns a process → use sandbox.py for resource limits
    └── Execute the tool function
```

**Verification:**
- Unit tests: verify that blocked patterns reject dangerous inputs (`rm -rf`, `sudo`, pipe to shell).
- Unit tests: verify that path validation catches traversal attacks (`../../../etc/passwd`), symlink escapes.
- Unit tests: verify that sandbox kills a process that exceeds timeout or memory.
- All tests use mocked processes — no real system commands are executed in tests.

**Dependencies:** Phase 1 (registry). Does not depend on Phase 2 — constraints are generic, not module-specific.

**Estimated size:** ~400 lines of production code, ~400 lines of tests (security code needs thorough test coverage).

---

### Phase 4: Skills System

**Goal:** Build the skill loader that reads Markdown files from module directories and the user's vault, controlled by the module's config.

**What is built:**

| File | Contents |
|---|---|
| `src/harle/tools/skills.py` | Skill loader — for each module, reads the `skills` list from config, resolves each name to a `.md` file (vault override first, then built-in), loads content, tracks token budget |
| Updates to `registry.py` | Registry calls skill loader during `register_module()`. New method: `get_skills_for_tools(tool_names)` returns loaded skill content for the modules that own those tools. |
| `config.example.yaml` updates | Add `skills` list to each module config block. Add `tool_skills` global section with `user_skills_dir` and `max_tokens_per_module`. |

**Skill resolution logic:**

```
For module "trello" with config skills: [triage, conventions]

For each skill name (e.g. "triage"):
  1. Check <vault>/tool_skills/trello/triage.md
     → exists? use it (user override)
  2. Else check src/harle/tools/trello/skills/triage.md
     → exists? use it (built-in)
  3. Else log warning: "Skill 'triage' not found for module 'trello'"

Count tokens for all loaded skills.
If total exceeds max_tokens_per_module → truncate, warn in log.
```

**Verification:**
- Unit tests: built-in skill loads when no user override exists.
- Unit tests: user vault skill overrides built-in with same filename.
- Unit tests: user vault skill with a new name (not in built-in) loads correctly.
- Unit tests: missing skill name logs a warning and does not crash.
- Unit tests: token budget enforcement truncates oversized skills.

**Dependencies:** Phase 1 (registry). Does not depend on Phase 2 or 3.

**Estimated size:** ~200 lines of production code, ~200 lines of tests.

---

### Phase 5: Orchestrator Wiring

**Goal:** Connect the Tool Module Layer to the Orchestrator's request pipeline. After this phase, agent tool calls go through the registry instead of being hardcoded.

**What changes:**

| Component | Change |
|---|---|
| **Orchestrator startup** | Reads `tool_modules` from `config.yaml`. For each enabled module: imports class, calls `initialize(config)`, calls `health_check()`, registers with `ToolRegistry`. |
| **Context Assembler** | Calls `registry.get_skills_for_tools(tool_names)` and includes skill content in the prompt at priority P1. |
| **Agent Runner** | Calls `registry.get_agent_tools(tool_names)` to get `FunctionTool` objects instead of importing tool functions directly. |
| **Orchestrator shutdown** | Calls `registry.shutdown_all()`. |
| **Run Logger** | Logs module name alongside tool name for each tool call. Logs constraint check results for tools with constraints. |

**What this replaces:** The Orchestrator's Section 6 ([orchestrator.md](./orchestrator.md)) now references this document for the full tool architecture. The Tool Module Layer owns the registry, approval flow, skills, and security constraints.

**Verification:**
- Integration test: start the Orchestrator with Web Search module enabled, send a request that triggers `search_web`, verify the full flow works — routing → context assembly (with skills) → agent execution → tool call → result.
- Integration test: start with a module whose health check fails, verify it is marked degraded and the system continues with other modules.
- Integration test: verify that `shutdown_all()` is called on server stop.

**Dependencies:** Phase 2 (at least one real module to wire). Phase 4 (skills) is recommended but not strictly required — the registry works without skills, it just returns empty skill content.

---

### Phase 6: Additional Modules

**Goal:** Build the remaining first-version modules using the established pattern. Each module is independent and can be built in any order.

| Module | What it does | Depends on | Priority |
|---|---|---|---|
| **Trello** | `search_cards`, `list_boards`, `get_card`, `create_card`, `update_card`, `move_card` via Trello API | Phase 5 | High — needed for Secretary role |
| **Vault** | `read_note`, `create_note`, `update_note`, `search_notes` over the user dataset | Phase 5 + Phase 3 (writes to local filesystem) | High — needed for all roles |
| **Scripts** | `run_script`, `list_scripts` — executes user scripts on the host | Phase 5 + Phase 3 (executes arbitrary code) | Medium — useful but dangerous, needs full security layer |

**For each module, the work is the same:**

1. Create the directory: `src/harle/tools/<name>/`
2. Implement `module.py` (class extending `BaseToolModule`), `tools.py` (tool functions), and optionally `client.py` (API wrapper).
3. Create `skills/` directory with 1–3 Markdown skill files.
4. Add the module's config block to `config.example.yaml`, including `constraints` for modules with local system access.
5. Write unit tests with mocked external dependencies.

**Important: the Scripts module must not be built before Phase 3 (security layer).** Unlike Web Search or Trello — where the damage surface is bounded by the external API — the scripts module executes commands on the host. It requires constraint validation (`allowed_commands`, `blocked_patterns`, `allowed_paths`) and the execution sandbox (timeout, memory limit) to be safe.

**Estimated size per module:** ~300–500 lines of production code, ~200–300 lines of tests, 1–3 skill files.

---

### Phase 7: config.example.yaml and Documentation

**Goal:** Ensure a fresh Harle deployment starts with secure, well-documented defaults.

**What is built:**

| Deliverable | Contents |
|---|---|
| `config.example.yaml` updates | Complete `tool_modules` section with all modules, recommended constraints for each, skill lists, and commented explanations |
| `docs/trd/architecture/tools.md` updates | Finalize this document to reflect the as-built system (any design changes discovered during implementation) |
| Built-in skill files | Review and finalize all `skills/*.md` files shipped with modules |

**Verification:**
- Copy `config.example.yaml`, set the required environment variables, start Harle. Everything should work with reasonable defaults.
- All constraint examples in the config are tested — the recommended `blocked_patterns` actually catch the dangerous commands they claim to block.

**Dependencies:** Phases 1–6 complete.

---

### Phase 8: MCP Compatibility (Optional)

**Goal:** Enable Harle to consume external MCP servers and optionally expose its own modules as MCP servers.

**What is built:**

| File | Contents |
|---|---|
| `src/harle/tools/mcp_provider.py` | `McpToolProvider` — adapter that connects to an external MCP server (via stdio or HTTP), calls `tools/list` and `tools/call`, and presents the results through the `BaseToolModule` interface so the registry can consume them |
| `src/harle/tools/mcp_export.py` | MCP server wrapper — takes any `BaseToolModule` and exposes it as an MCP server that external clients (Cursor, Claude) can connect to |

**When to build this:**
- **Import (consuming MCP servers):** build when a pre-existing MCP server is needed that is not worth reimplementing — e.g., a community-built GitHub MCP server with full API coverage.
- **Export (exposing Harle tools as MCP):** build when you want to use Harle's tools from Cursor, Claude, or another MCP-compatible client.

Neither is required for Harle to function. This phase is an interoperability enhancement.

**Dependencies:** Phase 5 (Orchestrator wiring).

---

### Phase dependency diagram

```
                    Phase 1
               Core Infrastructure
              (base.py, registry.py)
                    │
        ┌───────────┼───────────┐
        │           │           │
        ▼           ▼           ▼
    Phase 2     Phase 3     Phase 4
    Web Search  Security    Skills
    Module      Layer       System
        │           │           │
        └─────┬─────┘           │
              │                 │
              ▼                 │
          Phase 5               │
          Orchestrator          │
          Wiring                │
              │                 │
              ├─────────────────┘
              │
              ▼
          Phase 6
          Additional Modules
          (Trello, vault, scripts)
              │
              ▼
          Phase 7
          Config & Documentation
              │
              ▼
          Phase 8 (optional)
          MCP Compatibility
```

### Effort estimates

| Phase | Estimated effort | Can parallelize with |
|---|---|---|
| **1. Core infrastructure** | 1–2 days | — |
| **2. Web Search module** | 2–3 days | Phase 3, Phase 4 |
| **3. Security layer** | 2–3 days | Phase 2, Phase 4 |
| **4. Skills system** | 1–2 days | Phase 2, Phase 3 |
| **5. Orchestrator wiring** | 2–3 days | — |
| **6. Additional modules** | 2–3 days per module | Each module is independent |
| **7. Config and docs** | 1 day | — |
| **8. MCP compatibility** | 2–3 days | — |
| **Total (sequential)** | ~3–4 weeks | |
| **Total (with parallelism)** | ~2–3 weeks | Phases 2+3+4 in parallel |

Estimates assume a single developer working part-time. The critical path is: Phase 1 → Phase 2 → Phase 5 → Phase 6. Phases 3 and 4 can be built alongside Phase 2 to shorten the total timeline.
