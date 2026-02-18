Harle is a truly personal AI assistant.

It operates over a dataset you own and control — your notes, rules, project docs, preferences, and workflow templates, all stored as plain Markdown files you can read, edit, and version with Git. Unlike generic chatbots that forget you between sessions, Harle learns from your decisions: every clarification you give, every correction you make, every preference you express becomes part of its working knowledge. Over time it aligns with how *you* think and work — not through opaque fine-tuning, but through a transparent, human-readable knowledge base that you can inspect and change at any moment.

## Current scope (v0.2)

- **Go CLI** — session-first interface with `exec` and `init` commands
- **Python orchestrator** — FastAPI HTTP API forwarding requests to an LLM provider
- **Data layer** — PostgreSQL indexer, Markdown dataset reader, keyword search
- **Bootstrap** — `harle init` creates database tables, seeds the vault with starter files, and indexes everything

Not yet implemented: Whoosh/pgvector search, external integrations, Docker deployment, memory system, conversation history.

## Structure

```
harle-cli/                       # Go CLI
  cmd/harle/main.go              #   Entrypoint
  internal/commands/              #   root, exec, init commands
  internal/session/               #   Interactive session loop
  internal/client/                #   HTTP client + API types

src/harle/                        # Python orchestrator
  main.py                         #   FastAPI app factory
  config.py                       #   YAML / env-var configuration
  bootstrap.py                    #   Init: tables + seed dataset + indexing
  api/                            #   HTTP models and routes
  orchestrator/                   #   Request orchestration
  llm/                            #   LLM provider interface (OpenAI / echo)
  db/                             #   PostgreSQL models and connection
    models.py                     #     All tables (file_index, runs, artifacts,
                                  #     memories, conversations, messages, embeddings)
    connection.py                 #     Engine + session management
    file_index.py                 #     file_index CRUD
  dataset/                        #   Markdown vault reader
    reader.py                     #     Walk files, parse frontmatter
    frontmatter.py                #     YAML frontmatter parser
  search/                         #   Search algorithm
    engine.py                     #     Simple keyword search
    types.py                      #     SearchQuery / SearchResult
  indexing/                       #   Dataset → DB sync pipeline
    indexer.py                    #     Hash-based change detection + upsert
    hasher.py                     #     SHA-256 content hashing
```

User data (NOT in this repository — configured via `config.yaml` or env vars):

- `~/harle-vault/` — Markdown files: prompts, policies, workflows, knowledge, examples, logs
- PostgreSQL instance — file index, run logs, memories, conversation history

## Quick start

### 0. Requirements

**Python 3.10+**

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y python3 python3-venv python3-pip

# macOS (Homebrew)
brew install python@3.10

python3 --version   # verify: 3.10 or higher
```

**Go 1.22+**

```bash
# Ubuntu/Debian — download from https://go.dev/dl/
wget https://go.dev/dl/go1.22.6.linux-amd64.tar.gz
sudo rm -rf /usr/local/go && sudo tar -C /usr/local -xzf go1.22.6.linux-amd64.tar.gz
export PATH=$PATH:/usr/local/go/bin

# macOS (Homebrew)
brew install go

go version            # verify: 1.22 or higher
```

**PostgreSQL 16+** — either install natively or use Docker (step 2 below)

```bash
# Ubuntu/Debian
sudo apt install -y postgresql-16

# macOS (Homebrew)
brew install postgresql@16

psql --version        # verify: 16 or higher

# Or skip native install and use Docker in step 2
```

### 1. Install the Python orchestrator

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Set up PostgreSQL

You need a running PostgreSQL 16+ instance. Example with Docker:

```bash
docker run -d --name harle-db \
  -e POSTGRES_USER=harle \
  -e POSTGRES_PASSWORD=harle \
  -e POSTGRES_DB=harle \
  -p 5432:5432 \
  postgres:16
```

### 3. Configure Harle

Copy the example config and fill in your paths:

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml`:

```yaml
HARLE_HOST: "127.0.0.1"
HARLE_PORT: 8000
HARLE_LLM_PROVIDER: "openai"
HARLE_LLM_MODEL: "gpt-4o-mini"

HARLE_DATASET_PATH: "/home/you/harle-vault"
DATABASE_URL: "postgresql+psycopg2://harle:harle@localhost:5432/harle"
```

Set `OPENAI_API_KEY` as an environment variable (e.g. `export OPENAI_API_KEY="sk-..."`).
If the variable is not set, the app uses a local echo provider so you can still test the end-to-end flow.

### 4. Initialise the data layer

**Option A** — standalone (no server needed):

```bash
harle-init
```

**Option B** — via the CLI (server must be running):

```bash
harle-server &                   # start the server first
cd harle-cli
go build -o bin/harle ./cmd/harle
./bin/harle init
```

Both options do the same thing:
1. Create all PostgreSQL tables
2. Write starter files to your vault (prompts, policies, examples)
3. Index every `.md` file into the `file_index` table

### 5. Re-index after adding files

When you add new Markdown files to the vault, re-index so they become searchable:

```bash
# Standalone (no server needed)
harle-reindex

# Or via the API (server must be running)
curl -X POST http://127.0.0.1:8000/reindex
```

### 6. Start the server and use the CLI

```bash
harle-server
```

From another terminal:

```bash
cd harle-cli
go build -o bin/harle ./cmd/harle

# Non-interactive single task
./bin/harle exec "Summarize why modular architecture helps long-term maintenance"

# Interactive session
./bin/harle --context work
```

### 7. Try the search API

With the server running:

```bash
curl "http://127.0.0.1:8000/search?q=privacy"
curl "http://127.0.0.1:8000/search?q=researcher+agent&context=global"
```

## Running tests

The project uses **pytest** for unit testing. Tests cover configuration, frontmatter parsing, dataset reader, content hashing, search scoring, Pydantic models, LLM providers, orchestrator logic, and API endpoints. No external services (PostgreSQL, OpenAI) are required — all tests run with in-memory fixtures and the echo provider.

```bash
# Install test dependencies (once)
source .venv/bin/activate
pip install ".[test]"

# Run all tests
python -m pytest

# Verbose output with test names
python -m pytest -v

# Run a specific test file
python -m pytest tests/test_search_engine.py

# Run a specific test class or method
python -m pytest tests/test_reader.py::TestDatasetReader::test_read_all
```

Test structure:

```
tests/
  conftest.py              # Shared fixtures (temporary dataset directory)
  test_config.py           # Settings, _coerce, _load_yaml, load_settings
  test_frontmatter.py      # YAML frontmatter parser
  test_reader.py           # DatasetReader (list, read, edge cases)
  test_hasher.py           # SHA-256 content hashing
  test_search_engine.py    # Tokenizer, scorer, snippet extraction
  test_models.py           # Pydantic request/response validation
  test_providers.py        # EchoProvider
  test_orchestrator.py     # OrchestratorService, build_orchestrator
  test_api.py              # FastAPI routes via TestClient
```

## Session commands

- `/help` — list available commands
- `/quit` or `/exit` — close the session

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/run` | Send a message to the orchestrator |
| `POST` | `/init` | Create tables, seed dataset, run indexing |
| `POST` | `/reindex` | Re-index dataset files (no seeding or table creation) |
| `GET` | `/search?q=...` | Search the indexed dataset |
