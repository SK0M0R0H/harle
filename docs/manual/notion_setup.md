---
title: "Notion Integration — Setup & Usage Guide"
tags: [notion, setup, import, tools, integration, guide]
context: global
last_updated: 2026-03-14
summary: "Step-by-step guide for setting up the Notion integration, importing content, and using Notion tools."
---

# Notion Integration — Setup & Usage Guide

This guide explains how to connect Harle to your Notion workspace, import pages and databases into the vault, and use the Notion agent tools.

---

## Prerequisites

- A Notion account with content you want to import or access.
- A running Harle server (`harle-server`).
- The `harle` CLI installed.

---

## 1. Create a Notion Integration

1. Go to [https://www.notion.so/my-integrations](https://www.notion.so/my-integrations).
2. Click **New integration**.
3. Give it a name (e.g. "Harle").
4. Select the workspace you want to connect.
5. Under **Capabilities**, ensure **Read content** is enabled.
6. Click **Submit** to create the integration.
7. Copy the **Internal Integration Secret** (starts with `ntn_` or `secret_`).

## 2. Share Pages and Databases

Notion integrations only see content that has been explicitly shared with them.

1. Open a page or database in Notion.
2. Click the **...** menu in the top right.
3. Select **Add connections** (or **Connect to**).
4. Find and select your integration name (e.g. "Harle").
5. Repeat for each top-level page or database you want Harle to access.

Child pages and sub-pages inherit access from their parent.

**Can I add Harle to all pages at once?** No. Notion does not offer a way to grant an integration access to “everything I can see.” You must add the connection to each top-level page or database you want Harle to import or query. (On Notion Enterprise, workspace admins can manage integration access from **Settings → Connections**, but pages still need to be selected explicitly.)

## 3. Configure the Environment

Add the integration token to your environment:

```bash
export NOTION_API_TOKEN="ntn_your_token_here"
```

Or add it to your `.env` file:

```
NOTION_API_TOKEN=ntn_your_token_here
```

Restart the Harle server after setting the variable.

If import fails with a **timeout** (e.g. `ReadTimeout` or "Notion request failed"), the Notion API may be slow. The server uses a 120s default for Notion requests. To increase it, set `NOTION_TIMEOUT_SECONDS` (e.g. `300`) in the server environment and restart.

---

## Importing from Notion

### Basic Import

Import all accessible pages and databases:

```bash
harle import notion
```

### Dry Run (Preview)

Preview what would be imported without writing files:

```bash
harle import notion --dry-run
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | `false` | Preview without writing files |
| `--context` | `personal` | Context scope (`personal` or `work`) |
| `--target-dir` | `knowledge/` | Target directory within the vault |
| `--strategy` | `skip_existing` | Write strategy: `skip_existing`, `update_changed`, `force` |
| `--db-mode` | `pages` | Database import mode: `pages` or `table` |

### Database Import Modes

- **`pages`** (default): Each database row becomes a separate Markdown file with all property values in the frontmatter. Body content (blocks below properties) is included.
- **`table`**: Each database becomes a single Markdown file with all rows rendered as a Markdown table.

### Why does import take so long?

The importer talks to the Notion API with **many sequential requests**; there is no batching.

- **Search** — Paginated (one request per 100 pages, per 100 databases).
- **Each standalone page** — One or more requests to load blocks (and nested blocks up to `max_block_depth`), each level possibly paginated.
- **Each database** — One request for the schema, then paginated query for row IDs. For each row the API requires a **separate request per property** to resolve values (Notion does not return full row data in one call). In **pages** mode we also fetch block content for every row.

So a workspace with many pages or databases, or databases with many rows and columns, can mean hundreds or thousands of API calls. Notion’s latency and rate limits add up.

**Ways to speed things up or reduce load:**

- Use **`--db-mode table`** for large databases so you get one table file per database instead of one file per row (fewer block fetches).
- In `config.yaml` under `vault_imports.notion`, lower **`max_block_depth`** (e.g. `2`) to fetch fewer nested blocks; raise **`page_size`** (e.g. `100`) so each request returns more results. See `config.example.yaml` (``vault_imports.notion``) for options.
- Share only the pages/databases you need with the integration so the importer does less work.

### Examples

```bash
# Import with work context
harle import notion --context work

# Force overwrite existing files
harle import notion --strategy force

# Import databases as tables instead of individual pages
harle import notion --db-mode table
```

### What Gets Imported

**Standalone pages**: Pages not inside a database are saved to `knowledge/notion/pages/<title>-<id>.md`, where `<id>` is a short stable suffix from the Notion page ID so that two pages with the same title do not overwrite each other.

**Databases**: Each database is saved under `knowledge/notion/databases/<database_name>-<id>/` (or one file `<database_name>-<id>.md` in table mode). In `pages` mode, each row gets its own file `<row_title>-<id>.md` in that folder. The `<id>` suffix prevents collisions when titles repeat.

Each imported file includes:
- YAML frontmatter with title, tags, import metadata, and Notion IDs.
- The page content converted to Markdown (headings, lists, code blocks, tables, images, etc.).

---

## Using Notion Tools

When `NOTION_API_TOKEN` is set, Harle's agent has access to four read-only Notion tools:

### `notion_search`

Search for pages and databases by keyword.

### `notion_read_page`

Read a page's full content as Markdown.

### `notion_get_database`

Get a database's schema — column names and types. Useful for understanding what filters are available before querying.

### `notion_query_database`

Query a database with optional filters. Supports the Notion filter format:

- Select: `{"property": "Status", "select": {"equals": "Done"}}`
- Checkbox: `{"property": "Active", "checkbox": {"equals": true}}`
- Date: `{"property": "Due", "date": {"after": "2025-01-01"}}`
- Text: `{"property": "Name", "rich_text": {"contains": "project"}}`
- Compound: `{"and": [filter1, filter2]}`

Results are capped at 50 rows by default; the agent will note if results are truncated.

---

## Reference Mode (Future)

A reference import mode is planned but not yet implemented. In this mode, Harle would import only metadata and lightweight summaries, with the agent accessing full content live via the Notion tools. This avoids duplicating large datasets while keeping metadata searchable in the vault.

---

## Troubleshooting

**"Notion connection is not configured"**: Ensure `NOTION_API_TOKEN` is set and the server has been restarted.

**Empty results**: The integration only sees content explicitly shared with it. Go to each page/database in Notion and add the integration via the connections menu.

**Rate limits**: The Notion API has rate limits. For large workspaces, the import may take several minutes. The import client handles pagination automatically.
