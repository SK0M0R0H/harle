Harle is your most personal AI assistant.

## Prototype scope (v0.1)

This repository now contains a first minimal prototype with:

- Go CLI client
- Simple orchestrator (HTTP API) that only receives CLI requests and forwards them to an LLM provider

This prototype intentionally excludes:

- Data layer
- External integrations
- Docker/deployment infrastructure

## Structure

- `harle-cli/cmd/harle/main.go` - CLI entrypoint
- `harle-cli/internal/commands/` - root and `exec` commands
- `harle-cli/internal/session/` - minimal interactive session loop
- `harle-cli/internal/client/` - HTTP client and API types
- `src/harle/main.py` - FastAPI app entrypoint
- `src/harle/api/` - HTTP models and routes
- `src/harle/orchestrator/` - simple orchestration service
- `src/harle/llm/` - LLM provider interface + OpenAI/echo providers

## Quick start

1. Create Python env and install orchestrator:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

2. Optional: configure OpenAI credentials:

```bash
export OPENAI_API_KEY="your-key"
export HARLE_LLM_MODEL="gpt-4o-mini"
```

If `OPENAI_API_KEY` is not set, the app uses a local echo provider so you can still test end-to-end flow.

3. Run orchestrator server:

```bash
harle-server
```

4. Build and run Go CLI from another terminal:

```bash
cd harle-cli
go build -o bin/harle ./cmd/harle
./bin/harle exec "Summarize why modular architecture helps long-term maintenance"
./bin/harle --context work
```

Session mode commands:

- `/help`
- `/quit` or `/exit`
