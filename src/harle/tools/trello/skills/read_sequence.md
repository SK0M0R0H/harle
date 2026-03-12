---
title: "Trello Read Sequence"
---

Use Trello tools in a read-first sequence:

1. Start with `trello_list_boards` to discover available boards.
2. Identify the most relevant board by name/context.
3. Use `trello_list_cards` with that board ID to inspect card-level details.
4. If multiple boards may match, list cards for each and compare.

Guidelines:
- Keep calls read-only and avoid assumptions about missing fields.
- Report IDs and URLs when referencing boards/cards for traceability.
- If results are empty, explain whether this may indicate permission scope, an empty board, or a bad board ID.
