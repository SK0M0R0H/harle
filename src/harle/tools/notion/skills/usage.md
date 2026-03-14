---
title: "Notion Usage"
---

Use Notion tools in a discover-then-read sequence:

## Pages

1. Start with `notion_search` to find pages by keyword.
2. Use `notion_read_page` with the page ID to get the full Markdown content.
3. If the user asks about a specific page and the title is known, search for it first.

## Databases

1. Use `notion_search` to find databases (results include `object: "database"`).
2. Call `notion_get_database` with the database ID to see the schema (column names and types). This helps understand what filters are available.
3. Call `notion_query_database` to fetch rows. Use `filter_json` to narrow results.

### Filter examples for `notion_query_database`

- Select property: `{"property": "Status", "select": {"equals": "Done"}}`
- Checkbox: `{"property": "Active", "checkbox": {"equals": true}}`
- Date after: `{"property": "Due", "date": {"after": "2025-01-01"}}`
- Text contains: `{"property": "Name", "rich_text": {"contains": "project"}}`
- Compound: `{"and": [{"property": "Status", "select": {"equals": "Active"}}, {"property": "Priority", "select": {"equals": "High"}}]}`

### Row limits

- `max_rows` defaults to 50. If results show `truncated: true`, inform the user that more rows exist and offer to increase the limit.
- For large databases, recommend filtering to narrow results.

## Guidelines

- All Notion tools are read-only.
- Report page IDs and URLs for traceability.
- If results are empty, consider whether the integration may lack access    to the requested pages (utional sharing is    required in Notion).
