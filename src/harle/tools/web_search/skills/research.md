---
title: "Web Search — Research Skill"
tags: [web-search, research, tool-skill, query-strategy]
context: global
last_updated: 2026-02-25
summary: "Guides the LLM on how to structure web searches, evaluate results, and cross-reference information."
---

# Web Search Research

## When to Search

- Use `search_web` for factual questions, definitions, technical documentation,
  how-to guides, and any query where the user needs current information.
- Use `search_news` when the user asks about recent events, announcements,
  or anything time-sensitive.
- Use `fetch_page` to read the full content of a specific URL — typically
  after finding it via `search_web` or `search_news`.

## Crafting Effective Queries

1. **Be specific.** Prefer `"Python asyncio gather exception handling"` over
   `"Python async"`.
2. **Include context.** Add the technology, version, or domain when relevant:
   `"FastAPI 0.115 lifespan events"`.
3. **Use natural language for complex questions.** The search provider
   handles query reformulation internally.
4. **Split compound questions.** If the user asks about two unrelated topics,
   run two separate searches rather than one vague query.

## Using Results

- Present results as a concise summary with source attribution.
- When multiple results agree, state the consensus and cite 1–2 sources.
- When results conflict, note the disagreement and present both perspectives.
- Do not reproduce large blocks of copyrighted text.  Summarise and link.

## Cross-referencing

When accuracy matters (factual claims, statistics, dates):

1. Check whether at least two independent sources agree.
2. Prefer primary sources (official docs, original research) over
   secondary ones (blog posts, forums).
3. If a claim appears in only one source, qualify it: "According to [source]…"

## Limitations

- Search results may be outdated or biased.  State your confidence level
  when the evidence is thin.
- `fetch_page` may fail on pages that require JavaScript rendering or
  authentication.  If extraction returns empty content, tell the user
  and suggest an alternative approach.
- Respect the user's time: 3–5 results are usually enough.  Only increase
  `max_results` if the topic is niche and the first results are not
  relevant.
