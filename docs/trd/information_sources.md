---
title: "External Information Sources — Integration Options"
tags: [integrations, notion, obsidian, data-sync, external-sources, architecture, vault, ux]
context: global
last_updated: 2026-02-24
summary: "Lists target external information sources and evaluates integration strategies, focusing on the Notion database problem."
---

Typical user doesn't store all the info in the same vault. Which means Harle requires integrations with other information sources. 
Let's take the developer of Harle as a case for a first set of integrations.

1. Notion
2. Trello
3. Telegram 
4. X.com
5. mail (gmail first)

Notion is the closet source for the Harle's vault. However, it contains not only .md files but simple user-friendly databases as well. It means that even with some kind of import from the Notion, it will not work directly with set of md files. How to solve it?

The problem has two sides:
- **Machine-reading** — solvable via PostgreSQL; Harle can query structured data regardless of format.
- **Human-reading** — the user browsing the vault in Obsidian needs a friendly way to view database-like data, not raw CSV/YAML/frontmatter dumps.

### Obsidian plugins that solve the human-reading side

If Notion database rows are synced as individual `.md` files with frontmatter properties (one file per row), these plugins render them as interactive tables inside Obsidian:

**Dataview** — the foundation. Indexes frontmatter and inline fields across the vault. A DQL query like `TABLE status, due FROM "projects"` renders a live, sortable table. Read-only but lightweight and battle-tested (~10M downloads).

**DB Folder (Database Folder)** — builds on top of Dataview. Points at a folder of `.md` files and displays them as a Notion-style database grid. Supports inline editing, column types (text, number, select, checkbox, date), filtering, and sorting. Edits write back to frontmatter. Requires Dataview.

**Projects** — provides Table, Board, Calendar, and Gallery views over a folder of notes. Closest to Notion's multi-view databases. Originally by Marcus Olsson; the author discontinued it in 2025, but a community fork exists.

**DataLoom (formerly Notion-Like Tables)** — creates standalone database files inside the vault with its own storage format. Good for self-contained tables but less useful for data synced from Notion since it doesn't read frontmatter from other files.

The practical implication: syncing Notion databases as **one `.md` file per row with properties in frontmatter** makes the data both machine-readable (Harle indexes frontmatter) and human-readable (Dataview / DB Folder render it as a table). This approach works best with Options B, D, or E below.

### Options

**Option A — Notion API as a live data source (no import)**

Don't import Notion content into the vault at all. Instead, add Notion as a runtime integration: when Harle needs information, it queries the Notion API directly. Pages are fetched and converted to markdown on the fly; databases are queried as structured data and returned as context to the LLM.

- (+) Always up to date, no sync drift.
- (+) Databases stay queryable (filters, sorts, relations).
- (−) Requires network access and a Notion API token at runtime.
- (−) Slower context assembly — API latency on every request.
- (−) Notion content is not version-controlled or inspectable as plain files.

**Option B — Periodic sync with dual representation**

Run a scheduled or on-demand sync job. Notion pages become `.md` files in the vault. Notion databases become structured files (one `.csv` or `.yaml` per database) alongside a companion `.md` that describes the schema, purpose, and sample rows in prose.

- (+) Everything lands in the vault — readable, version-controlled, searchable.
- (+) Works offline once synced.
- (−) Databases lose their queryability — they become flat snapshots.
- (−) Sync conflicts if the same content is edited in both Notion and the vault.
- (−) Requires a sync tool or script to maintain.

**Option C — Hybrid: pages imported, databases queried live**

Import Notion pages as `.md` files into the vault (periodically or on demand) but keep Notion databases as a live integration. At search/query time, Harle queries both the local vault and the Notion API for database results, then merges context before sending it to the LLM.

- (+) Pages are local, fast, and version-controlled.
- (+) Databases remain fully queryable with filters and relations.
- (−) Two code paths: local vault search + Notion API queries.
- (−) Still depends on network for database content.

**Option D — Notion databases → PostgreSQL + vault metadata**

Sync Notion databases into Harle's own PostgreSQL instance as structured tables. Each synced database gets a companion `.md` file in the vault describing its schema, purpose, and relationship to other data. Notion pages are still imported as `.md` files.

- (+) Databases become first-class queryable data inside Harle's existing DB.
- (+) Vault `.md` files document what each table contains, keeping the knowledge base coherent.
- (+) No runtime dependency on the Notion API after sync.
- (−) Most complex to implement — need schema mapping and conflict resolution.
- (−) Risk of schema drift if the Notion database structure changes.

**Option E — Markdown tables as a "good enough" representation**

Convert each Notion database view into a Markdown table (one `.md` file per database or view). Properties become columns; each row is a table row. Loses relational queries but keeps everything in plain text.

- (+) Simplest approach — everything is `.md`, no new infrastructure.
- (+) LLMs can read and reason over Markdown tables reasonably well.
- (−) Large databases produce unwieldy files.
- (−) No filtering or sorting — the LLM sees the entire table every time.
- (−) Relations and rollups are flattened into plain text.