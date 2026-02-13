# Harle CLI — Architecture & Functionality

> The CLI is Harle's primary user interface — a session-based terminal application that connects to the Orchestrator. You launch it, you are in a session, and you stay there until you explicitly quit — like a Python shell, `psql`, or `node` REPL.

This document describes the CLI's internal architecture, its session-first interaction model, how it handles conversations, clarifications, and approvals, and the technology choices behind each part. It is written for someone who may not have deep backend experience.

For the overall system architecture, see [overview.md](./overview.md).  
For the Orchestrator (which the CLI talks to), see [orchestrator.md](./orchestrator.md).

---

## Where the CLI Sits

```
 YOUR MACHINE                                    REMOTE SERVER
┌─────────────────────────┐                     ┌───────────────────────┐
│                         │                     │                       │
│  ┌───────────────────┐  │    HTTP/JSON over   │  ┌─────────────────┐  │
│  │                   │  │      Tailscale      │  │                 │  │
│  │    harle CLI      │──┼─────────────────────┼─>│   Orchestrator  │  │
│  │    (Go binary)    │<─┼─────────────────────┼──│   (FastAPI)     │  │
│  │                   │  │                     │  │                 │  │
│  └───────────────────┘  │                     │  └─────────────────┘  │
│                         │                     │                       │
│  Single binary,         │                     │  Python, PostgreSQL,  │
│  no dependencies        │                     │  LLM, tools, search   │
└─────────────────────────┘                     └───────────────────────┘
```

The CLI is a **Go binary** that runs on your laptop, desktop, or any device with a terminal. It has zero knowledge of AI, databases, or search — it only knows how to:

1. Maintain an interactive session with a prompt where you type messages.
2. Send each message as JSON to the Orchestrator's HTTP API.
3. Receive the response (streamed in real-time).
4. Render it nicely in the terminal.
5. Handle interactive flows (clarification questions, approval prompts).
6. Keep the session alive until you explicitly quit.

This separation means the CLI is **very small** (~1–2 MB binary) and **very fast** (~10ms startup). All the heavy work happens on the server.

---

## Session-First Interaction Model

**The fundamental design decision:** Harle is always session-based. When you run `harle`, you enter a session — like launching `python`, `psql`, or `node`. You stay in that session, sending messages and receiving responses, until you explicitly type `/quit` or press `Ctrl+D`.

**Why session-first (not command-first):**

The previous design had two separate modes: `harle run` for one-shot tasks and `harle chat` for conversations. This created an artificial split. In practice:
- Most "one-shot" tasks naturally lead to follow-up questions ("can you also...", "actually, change that to...").
- Starting a new command for every follow-up is friction — you lose context and have to re-explain.
- The Orchestrator already maintains sessions on the server. The CLI should match this.

**The session model works like a Python shell:**

```
$ python              ← you launch the shell
>>> x = 1 + 2        ← you type, it responds
>>> print(x)          ← context carries over
3
>>> quit()            ← you explicitly leave

$ harle               ← you launch harle
harle> Find stalled tasks in Trello
[secretary] Found 7 stalled tasks...
harle> Reformulate the first one
[secretary] Here are options: ...      ← context carries over
harle> /quit           ← you explicitly leave
Session saved.
```

**Key rules:**
- **`harle` with no arguments** drops you into a new session.
- **Every message** is part of the current session. The Orchestrator has full conversation history.
- **To start a new session**, you must leave the current one (`/quit` or `/new`).
- **Sessions are saved automatically** and can be resumed later.
- **For scripting** (non-interactive, no session), use `harle exec "..."` — this is the escape hatch for automation.

---

## Internal Modules

The CLI consists of five internal modules. Each has one job.

```
┌──────────────────────────────────────────────────────────┐
│                       harle CLI                          │
│                                                          │
│  ┌─────────────┐  ┌─────────────────────────────────┐   │
│  │  Command    │  │  Session Manager (Bubbletea)    │   │
│  │  Parser     │─>│    ┌───────────┐ ┌───────────┐  │   │
│  │  (Cobra)    │  │    │  HTTP     │ │ Response   │  │   │
│  └─────────────┘  │    │  Client   │ │ Renderer   │  │   │
│                   │    └───────────┘ └───────────┘  │   │
│  ┌─────────────┐  │                                  │   │
│  │  Config     │  │    prompt → send → stream →      │   │
│  │  Manager    │  │    render → prompt → ...         │   │
│  └─────────────┘  └─────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

---

### 1. Command Parser (what does the user want?)

**What it does:** Handles the initial launch command and flags. Once inside a session, the Command Parser's job is minimal — the Session Manager takes over.

**Technology: [Cobra](https://cobra.dev/) + [pflag](https://github.com/spf13/pflag)**

**What is Cobra?**  
Cobra is a Go library for building CLI applications. If you have ever used `git`, `docker`, or `kubectl`, you have used a Cobra-powered CLI. It provides:
- **Subcommands** — like `harle`, `harle exec`, `harle config`.
- **Flags** — like `--context=work`, `--role=researcher`.
- **Auto-generated help** — `harle --help` works automatically.
- **Shell completions** — tab-completion in bash, zsh, fish, and PowerShell.
- **Argument validation** — rejects invalid inputs before any HTTP call is made.

**Why Cobra:**
- **De facto standard.** Cobra powers the CLIs for Docker, Kubernetes, GitHub CLI, Hugo, Helm, and hundreds of other tools. The patterns are familiar to anyone who uses a terminal.
- **Batteries included.** Help generation, completions, flag parsing, and argument validation come built-in. You focus on your commands, not on parsing logic.
- **Well-documented.** Extensive docs and thousands of real-world examples to learn from.

**Command tree (first version):**

```
harle                 Launch an interactive session (default action)
├── exec       Run a single task non-interactively (for scripting)
├── sessions   List or resume past sessions
│   ├── list   Show recent sessions
│   └── resume Resume a specific session
├── config     View or update CLI configuration
│   ├── set    Set a config value (e.g. server URL)
│   ├── get    Read a config value
│   └── list   Show all current configuration
├── auth       Authenticate with the Orchestrator
│   ├── login    Save authentication credentials
│   └── logout   Remove stored credentials
└── version    Print CLI version and server version
```

**Notice what changed:** There is no `run` vs. `chat` distinction. The root command (`harle`) is the session. The only non-session command is `exec` (the scripting escape hatch).

**Command details:**

#### `harle` — launch a session (the default)

This is the primary way to use Harle. Running `harle` with no arguments drops you into an interactive session.

```bash
# Start a new session (default context from config)
harle

# Start a new session in work context
harle --context=work

# Start a new session with a specific agent role
harle --role=researcher

# Resume the most recent session
harle --resume

# Resume a specific session
harle --resume=ses_2026-02-12_003
```

**Flags for `harle` (session launch):**

| Flag | Short | Default | What it does |
|---|---|---|---|
| `--context` | `-c` | `personal` | Set context scope: "work" or "personal" |
| `--role` | `-r` | (auto) | Start with a specific agent role |
| `--resume` | | (none) | Resume the last session, or a specific session by ID |
| `--verbose` | `-v` | `false` | Show metadata after every response |

**Inside a session — the full experience:**

```
$ harle --context=work

  Harle v0.1.0 │ context: work │ new session: ses_2026-02-12_004
  Type a message, or /help for commands.

harle> Find stalled tasks in Trello
[secretary] Found 7 stalled tasks. Here are the top 3:
  1. "Design API schema" — no activity for 21 days
  2. "Write onboarding doc" — no activity for 14 days
  3. "Review PR #42" — no activity for 18 days

harle> Can you suggest reformulations for the first one?
[secretary] Sure. "Design API schema" is broad. Here are options:
  a) "Draft the /run endpoint request/response schema"
  b) "List all entities that need API endpoints"
  c) "Review existing API designs in docs/ for reuse"

harle> Go with option (a) and create a Trello card for it
[secretary] I'd like to create this card:
  Board: Work
  List: To Do
  Title: Draft the /run endpoint request/response schema
  Due: 2026-02-19

  Approve? [y/n]
harle> y
[secretary] Card created. ✓

harle> Now research privacy solutions for institutional clients
[researcher] Switching to Researcher role for this task.
  Searching the web and your dataset...

  # Privacy Solutions for Institutional Clients
  ...

harle> /quit
Session saved: ses_2026-02-12_004 (6 messages, $0.012)
```

**Key behaviors inside a session:**
- **Every message is a follow-up.** The Orchestrator has the full conversation history. You do not need to repeat context.
- **Agent role can change automatically.** If you ask a research question after a task management question, the Router can switch from Secretary to Researcher mid-session. This is seamless — no need to start a new session.
- **Clarifications and approvals happen inline.** No separate flow — the session prompt handles everything.
- **The session is saved continuously.** If your terminal crashes or you close the window, you can resume with `harle --resume`.

**Session commands (slash commands):**

Inside a session, commands starting with `/` are interpreted by the CLI, not sent to the Orchestrator:

| Command | What it does |
|---|---|
| `/quit` or `/exit` | End the session, save it, and return to your shell |
| `/new` | End the current session and immediately start a new one |
| `/context work` | Switch context to "work" mid-session |
| `/context personal` | Switch context to "personal" mid-session |
| `/role researcher` | Switch agent role mid-session |
| `/history` | Show the session conversation so far |
| `/cost` | Show tokens used and estimated cost for this session |
| `/save filename.md` | Export the session to a Markdown file |
| `/retry` | Rerun the last request (useful if the response was poor) |
| `/status` | Show recent runs and their status |
| `/help` | Show available slash commands |

**Why `/new` exists:**

Sessions carry context. If you have been discussing Japan trip planning and then want to ask about a completely unrelated code review, the accumulated context might confuse the agent. `/new` cleanly ends the current session and starts fresh — like closing a Python shell and opening a new one.

```
harle> /new
Session saved: ses_2026-02-12_004 (6 messages, $0.012)

  Harle v0.1.0 │ context: work │ new session: ses_2026-02-12_005
  Type a message, or /help for commands.

harle> Review PR #42 on GitHub
[researcher] ...
```

#### `harle exec` — non-interactive single task (for scripting)

This is the escape hatch for automation, scripts, and piping. It sends a single request, prints the result, and exits — no session, no interactive prompt.

```bash
# Basic usage — message as argument
harle exec "Find all stalled tasks in Trello and suggest reformulations"

# Specify context
harle exec --context=work "Summarize today's completed tasks"

# Override agent role
harle exec --role=researcher "Compare privacy solutions"

# Skip clarification
harle exec --no-clarify "Create a weekly status report from Trello"

# Auto-approve all write actions
harle exec --yes "Add a reminder label to overdue Trello cards"

# Pipe input from a file
cat brief.md | harle exec --stdin

# Plain output for scripting (no Markdown rendering, no colors)
harle exec --plain "Generate weekly report" > report.md

# Fully non-interactive pipeline
cat brief.md | harle exec --stdin --no-clarify --yes --plain > result.md
```

**Flags for `harle exec`:**

| Flag | Short | Default | What it does |
|---|---|---|---|
| `--context` | `-c` | `personal` | Set context scope: "work" or "personal" |
| `--role` | `-r` | (auto) | Override agent role |
| `--no-clarify` | | `false` | Skip clarification (fail if server needs it) |
| `--yes` | `-y` | `false` | Auto-approve all write actions |
| `--no-stream` | | `false` | Wait for full response instead of streaming |
| `--stdin` | | `false` | Read the message from standard input |
| `--output` | `-o` | (terminal) | Save result to a file |
| `--plain` | | `false` | Strip all formatting (for piping) |
| `--verbose` | `-v` | `false` | Show metadata |

**`exec` does not create a session on the server.** Each `exec` call is a standalone request with no conversation history. This is intentional — scripts should not accumulate state.

#### `harle sessions` — manage past sessions

```bash
# List recent sessions
harle sessions list

# List with details (messages count, cost, duration)
harle sessions list --verbose

# Output:
#   ses_2026-02-12_004  work     6 msgs  $0.012  2h ago
#   ses_2026-02-12_003  personal 3 msgs  $0.004  5h ago
#   ses_2026-02-11_002  work     12 msgs $0.031  yesterday
```

Resuming happens from the main command: `harle --resume=ses_2026-02-12_004`.

#### `harle config` — manage configuration

```bash
# Set the server URL
harle config set server.url https://100.64.0.1:8000

# Set default context
harle config set defaults.context work

# View all config
harle config list

# View a specific value
harle config get server.url
```

#### `harle auth` — authentication

```bash
# Authenticate (stores token locally)
harle auth login

# Remove stored credentials
harle auth logout
```

---

### 2. HTTP Client (talk to the server)

**What it does:** Sends requests to the Orchestrator's API and receives responses. This is the only module that touches the network.

**Technology: Go standard library [`net/http`](https://pkg.go.dev/net/http) + [`encoding/json`](https://pkg.go.dev/encoding/json)**

**Why the Go standard library (no external HTTP library):**
- **Go's `net/http` is production-grade.** Unlike many languages where the standard HTTP client is basic and you need a library, Go's built-in HTTP client handles connection pooling, timeouts, TLS, retries, and HTTP/2 out of the box. Docker, Kubernetes, and Terraform all use it directly.
- **Zero dependencies.** No third-party library to install, update, or worry about breaking. The binary stays small and simple.
- **JSON support is built-in.** `encoding/json` handles serialization and deserialization. Combined with Go structs, it provides type-safe request/response handling with no extra tools.

**What the HTTP Client handles:**

| Responsibility | How it works |
|---|---|
| **Request serialization** | Converts command flags and arguments into the JSON format the Orchestrator expects |
| **Authentication** | Attaches the auth token (stored by `harle auth login`) to every request as a header |
| **Streaming (SSE)** | Reads Server-Sent Events line by line and passes each chunk to the Response Renderer in real-time |
| **Timeout handling** | Configurable timeout (default: 5 minutes). Long-running tasks use streaming so the connection stays alive |
| **Retry logic** | Retries on transient network errors (connection reset, DNS timeout) up to 3 times with backoff |
| **Error classification** | Translates HTTP status codes into user-friendly error categories (see Error Handling section) |

**How streaming works:**

When you type "Write a research report" inside a session, the response may take 30+ seconds. Without streaming, you would stare at a blank screen. With streaming:

```
Timeline:

  0s   CLI sends request
  2s   Server starts generating response
  2s   First chunk arrives: "# Privacy Solutions for Ins..."
  3s   Second chunk: "titutional Clients\n\n## Overview..."
  5s   More chunks arrive, displayed in real-time
  25s  Final chunk + "done" signal
  25s  CLI shows metadata (if --verbose): agent, tokens, cost
```

**How it works under the hood:**

The Orchestrator sends **Server-Sent Events (SSE)** — a standard HTTP streaming format where the server keeps the connection open and sends data chunks as they become available. The HTTP Client reads these chunks and forwards each one to the Response Renderer immediately.

```
CLI                                    Orchestrator
 │                                         │
 │  POST /run (Accept: text/event-stream)  │
 │────────────────────────────────────────>│
 │                                         │
 │  HTTP 200 (Content-Type: text/event-stream)
 │<────────────────────────────────────────│
 │                                         │
 │  data: {"type":"chunk","text":"# Pri"}  │
 │<────────────────────────────────────────│
 │  → render "# Pri"                       │
 │                                         │
 │  data: {"type":"chunk","text":"vacy S"} │
 │<────────────────────────────────────────│
 │  → render "vacy S"                      │
 │                                         │
 │  ...more chunks...                      │
 │                                         │
 │  data: {"type":"done","run_id":"..."}   │
 │<────────────────────────────────────────│
 │  → show completion, metadata            │
```

**Why SSE (not WebSockets):**
- **Simpler.** SSE is plain HTTP — it works through proxies, load balancers, and Tailscale without special configuration. WebSockets require a protocol upgrade and are harder to debug.
- **One-directional is enough.** During a `run`, data only flows from server to client. SSE is designed for exactly this. WebSockets are bidirectional, which adds complexity Harle does not need for streaming.
- **Reconnection built-in.** SSE clients automatically reconnect if the connection drops. With WebSockets, you have to implement this yourself.

Inside a session, each message you send is a separate HTTP call. Streaming (SSE) is used within each turn to show the response as it generates. Between turns, the connection is idle and the CLI waits for your next input.

---

### 3. Response Renderer (make it look good)

**What it does:** Takes the raw response from the server (JSON or streamed text) and displays it nicely in the terminal. This includes formatting, colors, Markdown rendering, and progress indicators.

**Technology: [Glamour](https://github.com/charmbracelet/glamour) (Markdown rendering) + [Lip Gloss](https://github.com/charmbracelet/lipgloss) (styling) from the [Charm](https://charm.sh/) ecosystem**

**What is the Charm ecosystem?**  
Charm is a collection of Go libraries for building beautiful terminal applications. If you have used `glow` (Markdown viewer), `gum` (shell script helper), or `soft-serve` (Git server), you have seen Charm libraries in action. They bring modern UI patterns to the terminal.

**Why Charm libraries:**
- **Beautiful defaults.** Glamour renders Markdown (headers, bold, lists, code blocks, tables) with colors and formatting that look great out of the box. Harle's agent responses are often structured text — without rendering, you see raw `#` and `**` symbols.
- **Terminal-aware.** They detect terminal width, color support (256-color, true-color, or no-color), and adapt automatically. Works in iTerm, Windows Terminal, VS Code integrated terminal, and basic terminals like xterm.
- **Same ecosystem.** Glamour, Lip Gloss, and other Charm tools are designed to work together. Consistent look, consistent API.
- **Go-native.** No CGO, no external dependencies. Compiles into the same single binary.

**What the renderer does for each response type:**

| Response type | How it renders |
|---|---|
| **Streamed text** | Characters appear in real-time, like typing. Markdown formatting is applied as complete blocks arrive. |
| **Clarification questions** | Questions displayed as a numbered list with a prompt for input. Visual distinction from regular output (different color/prefix). |
| **Approval requests** | Highlighted box showing the proposed action, with a `[y/n]` prompt. Shows what will happen if you approve. |
| **Error messages** | Red-tinted text with a clear error category and suggested fix. |
| **Metadata (--verbose)** | Dimmed text below the main response showing agent used, tools called, tokens consumed, estimated cost, duration. |
| **Status/list** | Formatted table showing recent runs with their status, agent, and timestamp. |

**Example of rendered output inside a session:**

```
$ harle --context=work --verbose

  Harle v0.1.0 │ context: work │ new session: ses_2026-02-12_004

harle> Find stalled tasks in Trello

 [secretary] Found 7 stalled tasks in your Work board. Here are the top 3:

 1. Design API schema
    No activity for 21 days. Last update: Jan 22.
    Suggestion: Break into "Draft /run endpoint schema"

 2. Write onboarding doc
    No activity for 14 days. Last update: Jan 29.
    Suggestion: Start with "Outline onboarding doc sections"

 3. Review PR #42
    No activity for 18 days. Last update: Jan 25.
    Suggestion: Rephrase as "Leave review on PR #42 by Friday"

 ─────────────────────────────────────────────────
 agent: secretary │ tools: trello_read │ tokens: 3,200
 cost: $0.002 │ duration: 3.4s │ run: run_2026-02-12_001

harle> _
```

**Plain mode (for `harle exec` scripting):**

For scripting and piping, `harle exec` supports a `--plain` flag that strips all formatting:

```bash
# Pipe output to a file
harle exec --plain "Summarize this week" > summary.md

# Use in a script
RESULT=$(harle exec --plain "List overdue tasks")
```

---

### 4. Session Manager (the core of the CLI)

**What it does:** The Session Manager is the primary module of the CLI. It runs the interactive session loop: display the prompt, read user input, send it to the server, render the response, handle clarifications and approvals, and repeat until the user quits.

Since Harle is session-first, the Session Manager is not a secondary feature — it **is** the main experience.

**Technology: [Bubbletea](https://github.com/charmbracelet/bubbletea)**

**What is Bubbletea?**  
Bubbletea is a Go framework for building interactive terminal applications based on The Elm Architecture — a pattern where your UI is a function of your state. It handles keyboard input, screen updates, and event handling in a clean, testable way.

**Why Bubbletea:**
- **Session is always interactive.** The CLI needs to handle continuous keyboard input, display streamed responses, manage the prompt, process slash commands, and handle mid-stream interruptions (clarifications, approvals). This is complex enough to require a framework.
- **Consistent with Charm ecosystem.** Since we already use Glamour and Lip Gloss for rendering, Bubbletea fits naturally. Same library family, same patterns.
- **Testable.** Bubbletea's architecture makes it possible to write automated tests for interactive flows — important for testing clarification and approval scenarios.
- **Handles concurrency.** While waiting for a streamed response, the user might press `Ctrl+C` to cancel. Bubbletea manages these concurrent events cleanly.

**The session loop:**

```
┌────────────────────────────────────────────────────────┐
│                    SESSION LOOP                         │
│                                                        │
│  1. Show prompt: harle>                                │
│  2. User types a message (or slash command)            │
│          │                                             │
│          ▼                                             │
│  3. Is it a slash command?                             │
│     ┌────┴────┐                                        │
│    yes        no                                       │
│     │          │                                       │
│     ▼          ▼                                       │
│  Execute    4. Send to Orchestrator via HTTP Client    │
│  locally       │                                       │
│  (/quit,       ▼                                       │
│   /new,     5. Server may respond with:                │
│   /help,       ├── Streamed text → render in real-time │
│   etc.)        ├── Clarification → show questions,     │
│     │          │   collect answers, resend             │
│     │          ├── Approval needed → show action,      │
│     │          │   ask [y/n], send decision            │
│     │          └── Error → display error message       │
│     │          │                                       │
│     │          ▼                                       │
│     │       6. Response complete. Loop back to 1.      │
│     │                                                  │
│     ▼                                                  │
│  /quit → save session, exit                            │
│  /new  → save session, start new session, loop back    │
│  other → execute and loop back to 1.                   │
└────────────────────────────────────────────────────────┘
```

**How clarifications work inside a session:**

Clarifications are seamless — they look like a normal conversation turn:

```
harle> Do something about the Japan trip
[secretary] I have a few questions before I start:
  1. Which Trello board contains the Japan trip tasks?
  2. Focus on: missing due dates, stalled tasks, or budget?
  3. Update tasks directly or prepare a summary?

harle> Work board, focus on stalled tasks, just a summary please
[secretary] Found 4 stalled Japan trip tasks...
```

Under the hood:
1. CLI sends the message to the Orchestrator.
2. Server responds with `"status": "clarification_needed"` and questions.
3. Session Manager renders the questions as an agent response.
4. User types answers naturally (it is just the next message in the session).
5. CLI sends the answers. Server proceeds with the task.

This is much more natural than the old design where clarification was a special interactive flow. In a session, it is just conversation.

**How approvals work inside a session:**

```
harle> Create a Trello card for the API schema task
[secretary] I'd like to create this card:
  Board: Work │ List: To Do
  Title: Draft the /run endpoint request/response schema
  Due: 2026-02-19

  Approve? [y/n]
harle> y
[secretary] Card created. ✓
```

Approvals arrive as a special SSE event mid-stream. The Session Manager pauses rendering, displays the approval prompt, collects the `y/n` answer, and sends it back. Streaming then resumes.

**Session state:**

The Session Manager tracks:

| State | What it contains |
|---|---|
| `session_id` | Unique identifier (assigned by server on first message) |
| `context` | Current context scope ("work" or "personal") |
| `agent` | Current agent role (can change automatically) |
| `message_count` | Number of messages sent in this session |
| `total_cost` | Running total of estimated cost |
| `pending_approval` | Whether we are waiting for a y/n answer |

**Session persistence:**

Sessions are saved server-side (in PostgreSQL). The CLI only stores the current `session_id` in a local state file (`~/.config/harle/session`). If the terminal is closed unexpectedly:
- The server-side session remains intact.
- Running `harle --resume` picks up where you left off.
- The conversation history is fully preserved.

**Non-interactive mode (`harle exec`):**

For scripting and automation, `harle exec` bypasses the Session Manager entirely. It uses a simple send-receive flow with no session state:

```bash
# Auto-approve everything (use with caution)
harle exec --yes "Update all overdue Trello cards with a reminder label"

# Fully non-interactive pipeline
cat brief.md | harle exec --stdin --no-clarify --yes --plain > result.md
```

---

### 5. Config Manager (remember settings)

**What it does:** Stores and retrieves CLI configuration — server URL, default context, authentication token, and display preferences. Settings persist between CLI invocations.

**Technology: [Viper](https://github.com/spf13/viper)**

**What is Viper?**  
Viper is a Go library for application configuration. It handles reading config files, environment variables, and command-line flags — and merging them with a clear priority order. It is the standard companion to Cobra (the command parser).

**Why Viper:**
- **Standard pairing with Cobra.** Cobra and Viper are built by the same author and designed to work together. Flags set in Cobra automatically flow into Viper, and config file values become available as flag defaults.
- **Multiple sources.** Viper reads from a config file, environment variables, and flags, with a clear precedence: flags > environment variables > config file > defaults. This is standard for CLI tools and gives you flexibility.
- **No reinventing.** Without Viper, you would manually parse YAML, check environment variables, merge with defaults, and handle missing values. Viper does all of this in a few lines.

**Config file location:**

Following platform conventions:

| OS | Config path |
|---|---|
| Linux | `~/.config/harle/config.yaml` |
| macOS | `~/Library/Application Support/harle/config.yaml` |
| Windows | `%APPDATA%\harle\config.yaml` |

**Config file structure:**

```yaml
# Server connection
server:
  url: "https://100.64.0.1:8000"    # Orchestrator URL (Tailscale IP)
  timeout: 300                       # Request timeout in seconds

# Authentication
auth:
  token: "harle_tok_..."             # Stored by 'harle auth login'

# Defaults
defaults:
  context: "personal"                # Default context (work | personal)
  verbose: false                     # Show metadata by default

# Session
session:
  auto_resume: false                 # If true, 'harle' resumes last session instead of starting new
  history_length: 50                 # Max messages to display with /history

# Display
display:
  theme: "auto"                      # auto | dark | light | plain
  width: 0                           # 0 = auto-detect terminal width
  markdown: true                     # Render Markdown in responses
```

**Environment variable overrides:**

Every config value can be overridden with an environment variable prefixed with `HARLE_`:

```bash
# Override server URL
export HARLE_SERVER_URL=https://192.168.1.100:8000

# Override default context
export HARLE_DEFAULTS_CONTEXT=work

# Override in a single command
HARLE_DEFAULTS_CONTEXT=work harle run "Check my tasks"
```

This is useful for:
- CI/CD environments where you do not want config files.
- Switching between servers (e.g. local dev vs. production) without editing files.
- Keeping the auth token in a secrets manager instead of a file.

---

## Authentication

**How the CLI proves its identity to the Orchestrator:**

The Orchestrator runs on a private network (Tailscale), which already provides network-level security — only your authenticated devices can reach it. But the CLI also needs application-level authentication to:
- Distinguish between users (if multiple people share the server later).
- Enable token revocation (if a device is lost).
- Support different permission levels in the future.

**Authentication flow:**

```
$ harle auth login
Server URL: https://100.64.0.1:8000
API Key: ************************************

Authenticating... ✓
Token saved to ~/.config/harle/config.yaml

$ harle run "Hello"
→ Token is automatically attached to every request
```

**How it works:**
1. `harle auth login` prompts for the server URL and an API key.
2. The CLI sends the API key to `POST /auth/token` on the Orchestrator.
3. The Orchestrator validates the key and returns a session token.
4. The CLI stores the token in the config file.
5. Every subsequent request includes the token in the `Authorization` header.

**First version:** The API key is a shared secret you configure on the server (in environment variables). This is simple and sufficient for a single-user setup behind Tailscale. In the future, this can be upgraded to OAuth or mTLS for multi-user scenarios.

---

## Error Handling

The CLI translates server errors and network problems into clear, actionable messages.

| Error | What the user sees | What to do |
|---|---|---|
| **Cannot connect** | `Error: cannot reach server at https://100.64.0.1:8000. Is Tailscale connected?` | Check Tailscale status, check if server is running |
| **Auth failed (401)** | `Error: authentication failed. Run 'harle auth login' to re-authenticate.` | Re-run `harle auth login` |
| **Server error (500)** | `Error: server error. Run 'harle status run_xxx' for details, or try again.` | Retry; check server logs if persistent |
| **Timeout** | `Error: request timed out after 300s. The task may still be running — check with 'harle status'.` | Use `harle status` to check; increase timeout in config |
| **Clarification failed** | `Error: the server asked for clarification but --no-clarify was set. Use an interactive session instead.` | Run `harle` (interactive session) instead of `harle exec --no-clarify` |
| **Invalid flags** | `Error: unknown flag --contxt. Did you mean --context?` | Cobra's built-in typo suggestions help fix the command |
| **Connection lost mid-stream** | `Warning: connection lost. Partial result shown above. Use 'harle --resume' to reconnect.` | Check network; the session is saved server-side and can be resumed |

**Exit codes:**

For scripting, the CLI uses standard exit codes:

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | General error (server error, unexpected failure) |
| `2` | Usage error (invalid flags, missing arguments) |
| `3` | Authentication error |
| `4` | Network error (cannot reach server) |
| `5` | Timeout |

This lets you use the CLI in scripts with proper error handling:

```bash
harle exec --plain --no-clarify --yes "Generate report" > report.md
if [ $? -ne 0 ]; then
  echo "Harle failed, falling back to manual process"
fi
```

---

## Build & Distribution

**How the CLI binary is built and delivered to your machines.**

**Build process:**

```bash
# Build for current platform
go build -o harle ./cmd/harle

# Cross-compile for different platforms
GOOS=linux   GOARCH=amd64 go build -o harle-linux-amd64   ./cmd/harle
GOOS=linux   GOARCH=arm64 go build -o harle-linux-arm64   ./cmd/harle
GOOS=darwin  GOARCH=arm64 go build -o harle-darwin-arm64  ./cmd/harle
GOOS=windows GOARCH=amd64 go build -o harle-windows.exe   ./cmd/harle
```

**Why this matters:**  
You have multiple machines (work laptop, personal computer). With Go, you build once and copy the binary — no runtime, no package manager, no installation step. If you add a new machine tomorrow, you copy one file and it works.

**Distribution (first version):**

For a single-user project, distribution is simple:
1. Build the binaries in CI (GitHub Actions) on every release tag.
2. Download the right binary for each machine.
3. Place it in your `$PATH` (e.g. `/usr/local/bin/harle`).

**Future:** If needed, distribution can be upgraded to a Homebrew tap (macOS), an APT repository (Linux), or a `go install` command.

**Version embedding:**

The build injects the version and commit hash into the binary:

```bash
$ harle version
harle v0.1.0 (commit: a1b2c3d, built: 2026-02-12)
server: v0.1.0 (https://100.64.0.1:8000)
```

This is done via Go's `-ldflags` at build time — a standard Go practice.

---

## Project Structure (Go)

```
harle-cli/
├── go.mod                        # Go module and dependencies
├── go.sum                        # Dependency lock file
├── Makefile                      # Build shortcuts (build, test, lint, cross-compile)
│
├── cmd/
│   └── harle/
│       └── main.go               # Entry point — initializes Cobra root command
│
├── internal/
│   ├── commands/                  # Command definitions (one file per command)
│   │   ├── root.go               # Root command → launches Session Manager
│   │   ├── exec.go               # 'harle exec' command (non-interactive)
│   │   ├── sessions.go           # 'harle sessions list/resume'
│   │   ├── config.go             # 'harle config' subcommands
│   │   ├── auth.go               # 'harle auth login/logout'
│   │   └── version.go            # 'harle version' command
│   │
│   ├── session/                   # Session Manager module (the core)
│   │   ├── manager.go            # Bubbletea session loop, state management
│   │   ├── prompt.go             # Input prompt with line editing
│   │   ├── slash.go              # Slash command parser (/quit, /new, /help, etc.)
│   │   └── state.go              # Session state (ID, context, agent, cost)
│   │
│   ├── client/                    # HTTP Client module
│   │   ├── client.go             # HTTP client with auth, retries, timeout
│   │   ├── streaming.go          # SSE stream reader
│   │   └── types.go              # Request/response Go structs (mirrors Orchestrator API)
│   │
│   ├── render/                    # Response Renderer module
│   │   ├── renderer.go           # Main renderer (Glamour + Lip Gloss)
│   │   ├── streaming.go          # Streaming renderer (displays chunks in real-time)
│   │   ├── table.go              # Table formatting (for sessions list, verbose metadata)
│   │   └── plain.go              # Plain text renderer (for exec --plain)
│   │
│   └── config/                    # Config Manager module
│       ├── config.go             # Viper initialization, config file paths
│       └── defaults.go           # Default values for all config keys
│
└── test/
    ├── session_test.go            # Session loop and slash command tests
    ├── client_test.go             # HTTP client tests (with mock server)
    ├── render_test.go             # Renderer output tests
    └── exec_test.go               # Non-interactive exec tests
```

**Why `internal/`?**  
In Go, the `internal/` directory is a language-level convention that prevents other Go modules from importing its contents. This enforces that the CLI's modules are private — they are implementation details, not a public library. Only the `cmd/harle/main.go` entry point (and tests) can use them.

**Key dependencies:**

| Package | Purpose |
|---|---|
| `github.com/spf13/cobra` | Command parsing, subcommands, flag handling |
| `github.com/spf13/viper` | Configuration management (file, env, flags) |
| `github.com/charmbracelet/glamour` | Markdown rendering in terminal |
| `github.com/charmbracelet/lipgloss` | Terminal styling (colors, borders, spacing) |
| `github.com/charmbracelet/bubbletea` | Session loop, interactive TUI framework |
| (Go standard library) | HTTP client, JSON, I/O — no external dependency needed |

Total external dependencies: **5 libraries**. The rest is Go standard library. This keeps the binary small and the supply chain minimal.

---

## Technology Choices Summary

| Decision | Choice | Key reason |
|---|---|---|
| **Language** | Go | Single binary, fast startup, industry standard for CLIs |
| **Command framework** | Cobra | De facto standard, subcommands, completions, help generation |
| **Config management** | Viper | Standard companion to Cobra, multi-source config merging |
| **HTTP client** | Go `net/http` | Production-grade built-in, zero dependencies |
| **Streaming** | SSE (Server-Sent Events) | Simple, works through proxies, auto-reconnect |
| **Markdown rendering** | Glamour | Beautiful terminal rendering, Go-native |
| **Terminal styling** | Lip Gloss | Consistent styling, Charm ecosystem |
| **Session loop** | Bubbletea | Core of the CLI — handles input, streaming, approvals, slash commands |
| **JSON handling** | Go `encoding/json` | Built-in, type-safe with structs |
| **Distribution** | Cross-compiled binaries | Copy one file, works everywhere, no install step |
