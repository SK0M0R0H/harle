---
title: "Modular Tool Architecture for AI Orchestrators — Research & Recommendation for Harle"
tags: [research, tools, plugins, skills, architecture, mcp, extensibility, integrations]
context: global
last_updated: 2026-02-23
summary: "Surveys industry approaches to modular tool/skill/plugin architecture in AI orchestrators, compares pros and cons, and recommends a unified Tool Module pattern for Harle."
---

# Modular Tool Architecture for AI Orchestrators

> This document surveys how major AI agent frameworks and orchestrators organize extensible capabilities (tools, skills, plugins, integrations), compares their architectural patterns, and recommends the approach best suited for Harle.

**Context:** Harle needs a modular, extensible system for capabilities like Trello integration, web search, script execution, Notion, Twitter, vault data management, and future additions. The current architecture document (`docs/trd/architecture/overview.md`) describes these under "External Integrations" in a simplified way. This research informs a proper design.

---

## 1. Terminology: Tools vs Skills vs Plugins vs Modules

The AI agent ecosystem uses these terms inconsistently. Before comparing architectures, it helps to pin down what each means in practice.

| Term | What it typically means | Who uses it |
|---|---|---|
| **Tool** | An executable function with defined inputs, outputs, and side effects. When an agent calls a tool, something happens: an API gets hit, a file gets written, a query gets run. | OpenAI, LangChain, MCP, nearly everyone |
| **Skill** | Packaged domain expertise that shapes how an agent thinks — instructions, templates, knowledge, behavioral patterns. Skills don't execute code directly; they provide context. | Anthropic (Agent Skills), Microsoft (Semantic Kernel, pre-2024), Cursor |
| **Plugin** | An organizational unit that bundles one or more tools, skills, configuration, and metadata into a discoverable package. | Microsoft (Semantic Kernel), OpenAI (ChatGPT Plugins, deprecated), Cursor |
| **Integration** | A connector to an external service (Trello, GitHub, Notion) — typically a set of tools wrapped around a third-party API. | CrewAI, Composio, n8n, general usage |
| **Extension** | An installable package that adds capabilities — follows naming conventions and common interfaces from the core framework. | AutoGen, VS Code, browser extensions |

**The practical reality:** From the LLM's perspective, all of these collapse into "tool" — an option presented to the model with a description and a way to invoke it. The distinctions matter for how *developers* organize, build, test, and deploy capabilities — not for what the model sees.

**Key insight from Arcade (2025):** "Whether you call it a skill, a tool, a function, or an MCP server, the agent sees a description and a way to invoke it. The taxonomy matters for your mental model and code organization. It doesn't change what the agent experiences."

---

## 2. Architectural Approaches in the Industry

### 2.1 Function-as-Tool (Decorator Pattern)

**Used by:** OpenAI Agents SDK, LangChain, CrewAI

The simplest approach: wrap a Python function with a decorator, and the framework auto-generates a JSON schema from the function's signature, type hints, and docstring. The schema is what the LLM sees.

```python
# OpenAI Agents SDK
@function_tool
def search_trello(board_id: str, status: str = "stalled") -> str:
    """Search Trello for cards matching the given status."""
    ...

agent = Agent(name="secretary", tools=[search_trello])
```

```python
# LangChain
@tool
def search_trello(board_id: str, status: str = "stalled") -> str:
    """Search Trello for cards matching the given status."""
    ...
```

**How it works:**
1. Developer writes a Python function with type hints and a docstring.
2. The decorator introspects the function and generates a JSON schema (parameter names, types, descriptions).
3. The schema is sent to the LLM alongside the prompt.
4. When the LLM decides to call the tool, the framework invokes the function with the generated arguments.

**Pros:**
- Minimal boilerplate — a decorator and a docstring is all you need.
- The function *is* the tool — no separate schema file, no manifest, no registration step.
- Easy to test (it is just a function).
- Type-checked at the Python level (mypy, Pydantic).
- Natural for Python developers.

**Cons:**
- No discoverability beyond "import and add to list." There is no mechanism for the system to find tools at runtime — they must be explicitly listed in agent definitions.
- No standard way to bundle related tools (e.g., all Trello operations) into a cohesive unit.
- No lifecycle management (init, shutdown, health checks).
- No configuration pattern — credentials and settings are handled ad-hoc (env vars, globals, closures).
- Tight coupling to the framework's decorator — switching from OpenAI SDK to LangChain means rewriting decorators.

---

### 2.2 Model Context Protocol (MCP)

**Used by:** Anthropic (Claude), OpenAI Agents SDK, Cursor, VS Code, many others

MCP is an open standard (JSON-RPC 2.0 over various transports) that defines how AI applications discover and invoke tools. It uses a client-server architecture: the orchestrator is an MCP client, and each tool (or group of tools) runs as an MCP server.

```
┌──────────────┐     JSON-RPC 2.0     ┌───────────────┐
│  Orchestrator │◄───────────────────►│  MCP Server   │
│  (MCP Client) │    stdio / HTTP     │  (Trello)     │
└──────────────┘                      └───────────────┘
```

**Protocol operations:**
- `tools/list` — client asks the server what tools are available.
- `tools/call` — client invokes a tool with arguments.
- `notifications/tools/list_changed` — server notifies client that its tool set changed.

**How it works:**
1. Each integration runs as a separate process (MCP server).
2. The orchestrator connects to the server via stdio (local) or HTTP (remote).
3. The orchestrator asks the server for its tool list (self-describing).
4. When the LLM decides to call a tool, the orchestrator forwards the request to the appropriate server.
5. The server executes the tool and returns the result.

**Pros:**
- **Language-agnostic** — an MCP server can be written in Python, TypeScript, Go, Rust, anything.
- **Process isolation** — each server runs in its own process. A crash in the Trello server does not take down the orchestrator.
- **Standardized discovery** — `tools/list` means every server is self-describing. No manual registration needed.
- **Portable** — the same MCP server works with Claude, Cursor, OpenAI SDK, and any other MCP-compatible host.
- **Growing ecosystem** — hundreds of pre-built MCP servers already exist.
- **Security boundary** — servers can run with restricted permissions, in containers, or on remote machines.

**Cons:**
- **Operational overhead** — each server is a separate process that must be started, monitored, and potentially restarted. For a personal project with 5–10 integrations, this means managing 5–10 processes.
- **Latency** — every tool call crosses a process boundary (or network). For local stdio servers the overhead is small (~1-5ms), but for HTTP-based servers it adds up.
- **Schema explosion** — a single MCP server can expose dozens of tools. GitHub's MCP server exposes 90+ tools, consuming >50,000 tokens of JSON schemas before the model starts reasoning. This wastes context window space and confuses the model.
- **No built-in configuration management** — MCP defines the protocol, not how servers get their credentials, settings, or state.
- **No lifecycle hooks** — the protocol does not standardize health checks, graceful shutdown, or initialization sequences beyond connection setup.
- **Debugging complexity** — errors cross process boundaries, making stack traces harder to follow.

---

### 2.3 Plugin System (Manifest-Driven)

**Used by:** Microsoft Semantic Kernel, Anthropic Agent Skills, Microsoft 365 Copilot, Cursor

A plugin is an organizational unit that bundles multiple tools, skills (domain knowledge), configuration, and metadata into a discoverable package. A manifest file (JSON or YAML) describes what the plugin provides.

```
trello-plugin/
├── manifest.json          # Name, version, description, capabilities
├── tools/
│   ├── list_cards.py
│   ├── create_card.py
│   └── move_card.py
├── skills/
│   └── triage.md          # Domain knowledge for task triage
└── config.schema.json     # Configuration schema (API key, board ID)
```

```json
{
  "name": "trello",
  "version": "1.0.0",
  "description": "Trello board management for task tracking",
  "tools": ["list_cards", "create_card", "move_card"],
  "skills": ["triage"],
  "config_schema": "config.schema.json"
}
```

**How it works:**
1. Plugins live in a known directory or are installed as packages.
2. The orchestrator scans for manifests and discovers available plugins.
3. Each plugin's tools are registered in the tool registry.
4. The orchestrator decides which plugins (and which tools within them) are relevant for a given task.
5. Configuration is loaded from a central config file or environment.

**Pros:**
- **Organized** — related tools, knowledge, and configuration live together.
- **Discoverable** — the orchestrator scans a directory and knows what is available without importing code.
- **Configurable** — each plugin declares its configuration schema, enabling validation and UI generation.
- **Supports both tools and skills** — a plugin can include executable functions *and* domain knowledge (prompts, templates, examples).
- **Version-controlled** — each plugin can have its own version, enabling independent evolution.
- **Enable/disable** — plugins can be toggled via configuration without code changes.

**Cons:**
- **More boilerplate** — every plugin needs a manifest, a directory structure, and potentially a config schema. For simple tools (a single function), this is heavyweight.
- **Discovery logic** — the orchestrator needs code to scan directories, parse manifests, validate schemas, and register tools. This is non-trivial to build correctly.
- **Custom standard** — unless you align with an existing format (e.g., MCP, OpenAI plugin spec), you are inventing your own plugin format that others cannot reuse.
- **Risk of over-engineering** — for a small system with 5–10 integrations, a full plugin system with manifest parsing may be premature.

---

### 2.4 Tool Registry (Central Aggregator)

**Used by:** agent-patterns library, custom implementations, Microsoft multi-agent reference architecture

A tool registry is a central component that aggregates tools from multiple sources (local functions, MCP servers, API wrappers) and provides a unified interface for discovery, invocation, and caching.

```
┌──────────────────────────────────────────┐
│              Tool Registry               │
│                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ Local    │ │  MCP     │ │  API     │ │
│  │ Provider │ │ Provider │ │ Provider │ │
│  └──────────┘ └──────────┘ └──────────┘ │
└──────────────────────────────────────────┘
```

**Core interface:**
```python
class ToolProvider(Protocol):
    async def list_tools(self) -> list[ToolDefinition]: ...
    async def execute_tool(self, name: str, params: dict) -> ToolResult: ...

class ToolRegistry:
    def register_provider(self, provider: ToolProvider) -> None: ...
    async def list_tools(self) -> list[ToolDefinition]: ...
    async def execute_tool(self, name: str, params: dict) -> ToolResult: ...
```

**How it works:**
1. Each tool source (local functions, MCP server, external API) implements the `ToolProvider` interface.
2. Providers are registered with the central `ToolRegistry`.
3. The registry aggregates all tools from all providers into a unified list.
4. When a tool is invoked, the registry routes the call to the correct provider.
5. The registry can add cross-cutting concerns: caching, logging, rate limiting, access control.

**Pros:**
- **Protocol-agnostic** — the registry abstracts over local functions, MCP servers, REST APIs, or any other source through a common adapter interface.
- **Single point of control** — logging, access control, rate limiting, and metrics apply uniformly to all tools.
- **Dynamic** — tools can be added or removed at runtime without restarting the orchestrator.
- **Concurrent execution** — the registry can execute multiple tool calls in parallel (reported 3.1x performance improvement).
- **Testable** — providers can be mocked individually.

**Cons:**
- **Extra abstraction layer** — adds indirection between the orchestrator and the tools. Every tool call goes through the registry, which adds a small amount of complexity and latency.
- **Must be built** — no major framework provides a production-ready tool registry out of the box. You write and maintain it yourself.
- **Risk of becoming a god object** — if the registry accumulates too many responsibilities (auth, caching, retry, logging, rate limiting), it becomes hard to maintain.
- **Naming conflicts** — when aggregating tools from multiple providers, two providers might expose tools with the same name. The registry needs a conflict resolution strategy.

---

### 2.5 Extension Package Pattern

**Used by:** AutoGen (0.4+), pip/PyPI ecosystem

Tools are distributed as separate installable Python packages that follow naming conventions and implement common interfaces from the core framework.

```
pip install autogen-ext-trello
pip install autogen-ext-websearch
```

```python
# autogen_ext_trello/tools.py
from autogen_core import BaseTool

class TrelloSearchTool(BaseTool):
    name = "trello_search"
    description = "Search Trello cards by status"
    ...
```

**How it works:**
1. Each integration is a separate Python package (published to PyPI or a private index).
2. Packages follow naming conventions (`harle-tool-*`) for discoverability.
3. Each package implements a common base class or protocol from the core framework.
4. The orchestrator discovers installed packages via entry points or import conventions.
5. Users install only the integrations they need.

**Pros:**
- **Independent lifecycle** — each integration has its own version, changelog, and release cycle.
- **Selective installation** — users only install what they need. No bloated core package.
- **Community contributions** — third parties can publish tools without modifying the core.
- **Standard Python tooling** — pip, setuptools, entry points, dependency management all work naturally.
- **Clean separation** — each package has its own tests, docs, and CI.

**Cons:**
- **High overhead for small projects** — publishing and maintaining separate PyPI packages for 5–10 internal integrations is excessive. Each package needs `pyproject.toml`, versioning, release automation.
- **Dependency management** — version constraints between the core and extension packages can create conflicts.
- **Discovery requires installation** — you cannot browse available tools until you install the package. No runtime discovery of capabilities before loading code.
- **Testing matrix** — the core must be tested against multiple extension versions.

---

### 2.6 Integration Platform (SaaS Layer)

**Used by:** Composio, Arcade, Zapier AI Actions

An external platform provides pre-built connectors to hundreds of services, managed authentication (OAuth, API keys), and a unified API that your orchestrator calls.

```
┌──────────────┐     API call      ┌───────────────────┐     OAuth     ┌──────────┐
│  Orchestrator │───────────────►  │  Composio / Arcade │─────────────►│  Trello  │
└──────────────┘                   └───────────────────┘              └──────────┘
```

**How it works:**
1. You sign up for the platform and connect your service accounts (Trello, GitHub, Notion, etc.).
2. The platform handles OAuth flows, token refresh, and credential storage.
3. Your orchestrator calls the platform's API to list tools and invoke actions.
4. The platform executes the action against the target service and returns results.

**Pros:**
- **Fastest time to integration** — 500+ services available out of the box. No writing API wrappers.
- **Managed auth** — OAuth flows, token lifecycle, and credential storage are handled by the platform. This is the hardest part of building integrations, and it is solved for you.
- **Multi-tenant** — designed for multiple users with separate credentials.
- **MCP gateway** — platforms like Composio expose their tools as MCP servers, so integration with MCP-compatible orchestrators is seamless.

**Cons:**
- **Vendor dependency** — your agent's ability to act depends on a third-party SaaS. If it goes down, your tools stop working.
- **Privacy** — your API credentials and tool call data flow through the platform's servers. For a personal assistant operating over private data, this is a significant concern.
- **Cost at scale** — free tiers are generous, but costs grow with usage. For a personal project, this is usually fine; for heavy automation, it adds up.
- **Limited customization** — the platform defines what actions are available and how they work. If you need a non-standard Trello operation, you may not be able to do it.
- **Latency** — every tool call makes a round trip through the platform's infrastructure.

---

## 3. Comparison Matrix

| Criterion | Function-as-Tool | MCP | Plugin System | Tool Registry | Extension Packages | Integration Platform |
|---|---|---|---|---|---|---|
| **Setup effort** | Very low | Medium | Medium-high | Medium | High | Very low |
| **Boilerplate per tool** | Minimal (decorator) | Medium (server) | Medium (manifest) | Low (class) | High (package) | None |
| **Runtime discovery** | No | Yes | Yes | Yes | Via entry points | Yes |
| **Process isolation** | No | Yes | No | Optional | No | Yes (remote) |
| **Portability** | Framework-locked | High (standard) | Custom | Custom | Framework-locked | Vendor-locked |
| **Grouping related tools** | Manual | Per server | Per plugin | Per provider | Per package | Per service |
| **Configuration mgmt** | Ad-hoc | Ad-hoc | Built-in | Custom | Per package | Managed |
| **Auth management** | Manual | Manual | Declarative | Manual | Manual | Managed |
| **Lifecycle hooks** | No | Partial | Yes | Yes | Yes | Managed |
| **Testability** | High | Medium | High | High | High | Low |
| **Privacy** | Full local | Full local | Full local | Full local | Full local | Data leaves machine |
| **Scales to 50+ tools** | Poorly | Well | Well | Well | Well | Very well |
| **Good for 5–10 tools** | Excellent | Overkill alone | Good | Good | Overkill | Depends on privacy needs |

---

## 4. What the Industry Has Learned (Practical Insights)

### 4.1 Tool Count Should Be Low

Successful agent systems use fewer tools than expected. Anthropic's engineering found that a single GitHub MCP server exposing 90+ tools consumed 50,000+ tokens of JSON schemas before reasoning began. The recommendation: **expose 5–15 well-designed tools per agent context**, not every possible operation.

This means the architecture must support *filtering* — having many tools available in the system but only exposing a relevant subset to the LLM for a given task.

### 4.2 Skills (Domain Knowledge) Are Separate from Tools (Execution)

Tools answer "what can the agent do?" Skills answer "what does the agent know?" Harle already separates these — agent prompts and policies live in the vault (skills/knowledge), while integrations provide execution capability (tools). The architecture should preserve this separation rather than conflating them.

### 4.3 Authentication Is the Production Killer

~70% of AI projects fail to reach production, and integration auth complexity is a primary culprit. For a personal assistant like Harle, the auth surface is smaller (one user, one set of credentials), but it still needs a clean pattern: API keys in config, OAuth token management, and credential isolation.

### 4.4 Single-Agent Simplicity Beats Multi-Agent Complexity

Cognition (Devin) explicitly recommends against multi-agent architectures in 2025: "Running multiple agents in collaboration only results in fragile systems." Harle's current design (one orchestrator, multiple agent *roles*) is aligned with this insight. The tool architecture should keep this simplicity — one registry, one tool invocation path, no tool-to-tool communication.

### 4.5 The Framework Lock-In Tax

Teams that build directly on one framework's tool format (OpenAI's `@function_tool`, LangChain's `@tool`) face rewrite costs when switching. The recommended pattern: write tools as plain Python classes/functions with a thin adapter layer for the framework of the day.

---

## 5. Recommendation for Harle: Unified Tool Module Pattern

### 5.1 The Name: "Tool Module"

After reviewing the terminology landscape, the recommended term for Harle is **Tool Module** (or just **module** in casual usage).

**Why "Tool Module":**
- "Tool" — because every module ultimately exposes executable capabilities to the LLM. This aligns with the dominant industry term and avoids confusion.
- "Module" — because each unit is a self-contained package of related tools, configuration, and metadata. It is more than a single function (unlike "tool") and less heavyweight than "plugin" or "extension" (which imply installable packages or manifest parsing).
- Avoids the loaded connotations of "plugin" (ChatGPT plugins are deprecated), "skill" (Anthropic-specific, means prompt-based expertise), or "integration" (implies external API only, but some modules are internal — like vault management or script execution).

### 5.2 The Architecture

The recommended architecture combines the best elements from the approaches above:

1. **Tool Module (Section 2.3 — Plugin System, simplified)** — each capability is a directory following a standard structure, with a Python class that self-describes.
2. **Tool Registry (Section 2.4)** — a lightweight central aggregator that discovers, registers, and routes to modules.
3. **MCP compatibility (Section 2.2)** — modules can optionally be exposed as MCP servers, but this is an export layer, not the primary internal interface.
4. **Function-as-Tool wiring (Section 2.1)** — the registry converts module tools into the OpenAI Agents SDK format for actual LLM interaction.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Orchestrator                             │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    Tool Registry                          │  │
│  │                                                           │  │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐     │  │
│  │  │ Trello  │  │   Web   │  │ Scripts │  │  Vault  │ ... │  │
│  │  │ Module  │  │ Search  │  │ Module  │  │ Module  │     │  │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘     │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                  │
│                    ┌─────────▼──────────┐                       │
│                    │  OpenAI Agents SDK │                       │
│                    │  (function tools)  │                       │
│                    └────────────────────┘                       │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 Tool Module Structure

Every tool module follows the same directory layout:

```
src/harle/tools/
├── __init__.py
├── registry.py              # ToolRegistry class
├── base.py                  # BaseToolModule protocol/ABC
│
├── trello/
│   ├── __init__.py
│   ├── module.py            # TrelloModule(BaseToolModule)
│   ├── client.py            # Trello API wrapper
│   └── tools.py             # Individual tool functions
│
├── web_search/
│   ├── __init__.py
│   ├── module.py            # WebSearchModule(BaseToolModule)
│   ├── client.py            # Tavily/SearXNG wrapper
│   └── tools.py             # search_web, search_news, etc.
│
├── scripts/
│   ├── __init__.py
│   ├── module.py            # ScriptsModule(BaseToolModule)
│   └── tools.py             # run_script, list_scripts, etc.
│
├── vault/
│   ├── __init__.py
│   ├── module.py            # VaultModule(BaseToolModule)
│   └── tools.py             # update_note, create_note, etc.
│
├── notion/
│   └── ...
│
└── twitter/
    └── ...
```

### 5.4 Base Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict          # JSON Schema
    module_name: str


class BaseToolModule(ABC):
    """Base class that every tool module implements."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique module identifier (e.g. 'trello', 'web_search')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for logging and debugging."""
        ...

    @abstractmethod
    async def initialize(self, config: dict) -> None:
        """Set up clients, validate credentials, prepare state."""
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Clean up resources."""
        ...

    @abstractmethod
    def list_tools(self) -> list[ToolDefinition]:
        """Return the tools this module provides."""
        ...

    @abstractmethod
    async def execute(self, tool_name: str, params: dict) -> str:
        """Execute a tool by name with the given parameters."""
        ...

    async def health_check(self) -> bool:
        """Optional: verify the module is operational."""
        return True
```

### 5.5 How It Works End-to-End

**Startup:**
1. The Orchestrator reads `config.yaml` to see which modules are enabled and their settings.
2. For each enabled module, it imports the module class, calls `initialize(config)`, and registers it with the `ToolRegistry`.
3. The registry calls `list_tools()` on each module and builds a unified tool catalog.

**Request processing:**
1. The Orchestrator receives a user request.
2. Based on the agent role and task, it selects a subset of tools from the registry (not all — see "tool count should be low" above).
3. Selected tools are converted to OpenAI Agents SDK `FunctionTool` objects and passed to the agent.
4. When the LLM calls a tool, the SDK invokes the registry's `execute()`, which routes to the correct module.

**Shutdown:**
1. The Orchestrator calls `shutdown()` on each registered module for clean resource release.

### 5.6 Configuration

```yaml
# In config.yaml
tool_modules:
  trello:
    enabled: true
    api_key: ${TRELLO_API_KEY}
    api_token: ${TRELLO_API_TOKEN}
    default_board: "Work Tasks"
    mode: read_only               # read_only | propose | auto

  web_search:
    enabled: true
    provider: tavily              # tavily | bing | searxng
    api_key: ${TAVILY_API_KEY}

  scripts:
    enabled: true
    scripts_dir: "${HARLE_VAULT_PATH}/scripts"
    allowed_extensions: [".py", ".sh"]
    timeout_seconds: 30

  vault:
    enabled: true
    vault_path: ${HARLE_VAULT_PATH}

  notion:
    enabled: false                # Disabled until needed
    api_key: ${NOTION_API_KEY}

  twitter:
    enabled: false
    # ...
```

### 5.7 Why This Combination Works for Harle

| Harle Constraint | How This Architecture Addresses It |
|---|---|
| **Small scale (5–15 modules)** | No need for separate packages or heavy plugin manifests. Each module is a directory with a Python class — minimal overhead. |
| **Single developer** | All modules live in the same repository. No multi-repo management, no PyPI publishing, no version matrix. |
| **Privacy-first** | Everything runs locally. No SaaS integration platform. Credentials stay in local config. |
| **OpenAI Agents SDK** | The registry converts module tools to SDK function tools — a thin adapter, not a framework rewrite. |
| **Future MCP compatibility** | Modules can be wrapped as MCP servers later (each module already implements `list_tools()` and `execute()`, which maps directly to MCP's `tools/list` and `tools/call`). |
| **Selective tool exposure** | The registry holds all tools, but the orchestrator picks a subset per request. This keeps token usage low. |
| **Needs lifecycle management** | `initialize()` / `shutdown()` / `health_check()` are part of the base class. |
| **Configurable per deployment** | Each module reads its config from a central `config.yaml`. Enable/disable is a boolean. |
| **Heterogeneous capabilities** | The same pattern works for external APIs (Trello, Notion), local operations (vault, scripts), and search (web search). |

### 5.8 MCP as an Export Layer (Not the Primary Interface)

Harle's overview doc already mentions MCP for integrations. The recommended approach:

- **Internally**, modules communicate with the orchestrator through the `BaseToolModule` interface and the `ToolRegistry`. This is fast (in-process), simple to debug, and requires no protocol overhead.
- **Externally**, any module can be exposed as an MCP server for use by other clients (Cursor, Claude, other tools). This is an optional wrapper — not every module needs it.
- **Incoming MCP**: the registry can also consume external MCP servers as a `ToolProvider` — for tools that already exist as MCP servers (e.g., filesystem, GitHub) and do not need custom wrappers.

```
                    ┌─────────────────────┐
                    │    Tool Registry     │
                    │                      │
    Internal:       │  ┌──────────────┐   │      External (optional):
    BaseToolModule ─┤  │ Trello Module│   │──── MCP Server wrapper
                    │  └──────────────┘   │     (for Cursor, Claude, etc.)
                    │  ┌──────────────┐   │
    BaseToolModule ─┤  │ Vault Module │   │
                    │  └──────────────┘   │
                    │  ┌──────────────┐   │
    MCP Provider ───┤  │ GitHub (MCP) │   │     Consuming existing MCP servers
                    │  └──────────────┘   │
                    └─────────────────────┘
```

This gives Harle the simplicity of in-process tools for its own modules, the interoperability of MCP for external ecosystem tools, and the ability to share its modules with MCP-compatible clients — all without forcing every tool to be an MCP server.

---

## 6. Comparison with Current "External Integrations" Section

The current architecture document (`overview.md`, Section 6) describes integrations in a flat, per-service structure: Trello, Web Search, and a table of planned integrations. This works as a feature description but does not define a reusable pattern.

| Current approach | Recommended "Tool Module" approach |
|---|---|
| Each integration described individually | All modules follow the same `BaseToolModule` interface |
| No standard directory structure | Every module uses the same layout: `module.py`, `tools.py`, `client.py` |
| No lifecycle management | `initialize()`, `shutdown()`, `health_check()` in base class |
| No central registry | `ToolRegistry` discovers, aggregates, and routes |
| MCP mentioned as the wire format | MCP is an optional export layer; internal interface is simpler |
| Configuration mentioned but not standardized | Each module declares its config schema; all config lives in `config.yaml` under `tool_modules` |
| No concept of enabling/disabling | Each module has an `enabled` flag in config |
| No tool filtering per agent | Registry holds all tools; orchestrator selects a subset per request |

---

## 7. Migration Path

The tool module architecture does not require rewriting the current Harle codebase. It can be introduced incrementally:

1. **Define `BaseToolModule` and `ToolRegistry`** — create `src/harle/tools/base.py` and `src/harle/tools/registry.py`. These are small files (~100 lines each).
2. **Convert Trello integration** — wrap the existing Trello API calls in a `TrelloModule` class following the base interface. Move them to `src/harle/tools/trello/`.
3. **Convert Web Search** — same pattern, `WebSearchModule` in `src/harle/tools/web_search/`.
4. **Wire into the Orchestrator** — replace direct tool references with registry-based lookup. The orchestrator asks the registry for tools instead of importing them directly.
5. **Add new modules** — each new integration (Notion, Twitter, scripts, vault) follows the same template. Copy the directory structure, implement the interface, add config.

No big-bang migration. Each step is independently testable and deployable.

---

## 8. Sources

| Source | What it contributed |
|---|---|
| [OpenAI Agents SDK — Tools](https://openai.github.io/openai-agents-python/tools/) | Function-as-tool pattern, MCP integration, tool categories |
| [MCP — Architecture](https://modelcontextprotocol.io/docs/learn/architecture) | Protocol design, client-server model, transport options |
| [MCP — Tools](https://modelcontextprotocol.io/docs/concepts/tools) | Tool discovery, invocation protocol, safety requirements |
| [Semantic Kernel — Plugins](https://devblogs.microsoft.com/semantic-kernel/guest-blog-orchestrating-ai-agents-with-semantic-kernel-plugins-a-technical-deep-dive/) | Plugin architecture, orchestration patterns, LLM-driven tool selection |
| [Semantic Kernel — Skills to Plugins](https://devblogs.microsoft.com/semantic-kernel/skills-to-plugins-fully-embracing-the-openai-plugin-spec-in-semantic-kernel/) | Naming evolution from "skills" to "plugins" |
| [AutoGen — Extensions](https://microsoft.github.io/autogen/dev/user-guide/extensions-user-guide/create-your-own.html) | Extension package pattern, naming conventions, interface contracts |
| [agent-patterns — Tool System](https://agent-patterns.readthedocs.io/en/latest/core/tools.html) | ToolProvider/ToolRegistry pattern, concurrent execution |
| [Arcade — Skills vs Tools](https://www.arcade.dev/blog/what-are-agent-skills-and-tools) | Industry terminology analysis, production insights, auth-first perspective |
| [Composio](https://composio.dev/) | Integration platform pattern, managed auth, MCP gateway |
| [LangChain — Architecture](https://python.langchain.com/docs/concepts/architecture) | Tool binding, toolkit hierarchy, runnable interface |
| [CrewAI — Production Architecture](https://docs.crewai.com/en/concepts/production-architecture) | Flow-first approach, role-based agents, structured outputs |
| [AI Agent Frameworks Compared (2026)](https://arsum.com/blog/posts/ai-agent-frameworks/) | Cross-framework comparison, adoption statistics |
| [Microsoft Multi-Agent Reference Architecture — Agent Registry](https://microsoft.github.io/multi-agent-reference-architecture/docs/agent-registry/Agent-Registry.html) | Registry components, discovery patterns |
| [A Practical Guide for Agentic AI Workflows (arXiv 2512.08769)](https://arxiv.org/abs/2512.08769) | Tool-first design, clean separation principles, containerized deployment |
