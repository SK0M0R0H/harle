# Web Search Module

The Web Search module provides Harle agents with the ability to search the web
and extract content from web pages.  It is the first tool module built on the
Tool Module Layer infrastructure (Phase 2 of the implementation plan).

## Tools

| Tool | Permission | Description |
|---|---|---|
| `search_web` | `read` | General-purpose web search.  Returns titles, URLs, content snippets, and optionally a synthesised answer. |
| `search_news` | `read` | News-focused search biased towards recent publications. |
| `fetch_page` | `read` | Fetches a URL and extracts its readable text content. |

All tools are read-only and require no user approval.

## Supported Providers

| Provider | Status | Notes |
|---|---|---|
| **Tavily** | Implemented | Primary provider.  Requires `TAVILY_API_KEY`. |
| **Bing** | Stub | Not yet implemented.  Will use Bing Web Search API. |
| **SearXNG** | Stub | Not yet implemented.  Self-hosted meta-search engine. |

Provider selection is config-driven — swap `provider` in `config.yaml` without
changing code.

## Configuration

```yaml
tool_modules:
  web_search:
    enabled: true
    provider: tavily            # tavily | bing | searxng
    api_key: ${TAVILY_API_KEY}
    max_results: 5              # default results per query (1–10)
    timeout_seconds: 30         # HTTP timeout
    mode: auto                  # read-only module, auto is safe
    skills: [research]          # built-in skill files to load
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `TAVILY_API_KEY` | Yes (for Tavily) | API key from [tavily.com](https://tavily.com) |

## Directory Layout

```
src/harle/tools/web_search/
├── __init__.py        # Package init
├── module.py          # WebSearchModule(BaseToolModule)
├── client.py          # Async HTTP wrapper (httpx)
├── tools.py           # Tool functions (search_web, search_news, fetch_page)
├── skills/
│   └── research.md    # Built-in research skill
└── README.md          # This file
```

## Skills

### Built-in: `research`

Located at `skills/research.md`.  Teaches the LLM how to craft effective
search queries, evaluate and cross-reference results, and handle edge cases.

### User Override

Place a custom `research.md` in your vault at:

```
<vault>/tool_skills/web_search/research.md
```

This overrides the built-in version.  You can also add entirely new skill
files (e.g. `sources.md` with preferred/blocked domains) and reference them
in the config's `skills` list.

## Usage (Standalone Testing)

The module can be tested in isolation without the Orchestrator:

```python
import asyncio
from harle.tools.web_search.module import WebSearchModule

async def main():
    module = WebSearchModule()
    await module.initialize({
        "provider": "tavily",
        "api_key": "tvly-...",
        "max_results": 3,
    })

    # Health check
    healthy = await module.health_check()
    print(f"Healthy: {healthy}")

    # Call a tool function directly
    from harle.tools.web_search.tools import search_web
    result = await search_web("Python 3.12 new features")
    print(result)

    await module.shutdown()

asyncio.run(main())
```

## Design Notes

- **Module-level client accessor.**  Tool functions are plain `async def`
  functions (not methods on a class) so the OpenAI Agents SDK can
  introspect their signatures.  They access the HTTP client via
  `client.get_client()`, which is set during `WebSearchModule.initialize()`.

- **No default constraints.**  Web search is an API-only, read-only module.
  Its damage surface is bounded by the external API, so no `allowed_paths`,
  `blocked_patterns`, or other local-system constraints are needed.

- **Not wired to the Orchestrator yet.**  This module is built and testable
  in isolation.  Orchestrator wiring happens in Phase 5.
