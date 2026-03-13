---
title: "Investigation — Trello 'Today' List Not Found (Cards Return List IDs Only)"
tags: [investigation, trello, tools, list-names, id-list, ux]
context: global
last_updated: 2026-03-13
summary: "Documents why the agent cannot return cards from a named list (e.g. 'Today'): tools expose only list IDs, not list names; root causes and fix options."
---

# Investigation: Trello "Today" List Not Found — Agent Returns List IDs Instead of List Names

**Date:** 2026-03-13

**Goal of this file:** Use during implementation to understand why the agent cannot fulfill "give me cards in the Today list" and what to change so list names (e.g. "Today") can be used.

---

## 1. Problem

User asked the agent to use Trello and return cards from the **"Today"** list on their board. The board does have a list named "Today".

**Expected behaviour:** The agent lists boards, finds the right board, finds the list named "Today", and returns the cards in that list.

**Actual behaviour:** The agent listed the board and all cards on it, but the Trello tool returns cards with **`id_list`** (opaque IDs) only — **no list names**. The agent could not map "Today" to any `id_list`, so it grouped cards by `id_list` with sample card titles and asked the user to identify which ID corresponds to "Today".

Example agent reply (summary):

- "I need you to confirm which list ID is the 'Today' list."
- It then showed several `id_list` values with sample cards (e.g. "id_list = 5d8bc44dd0aab42f12662a18 (many personal/to-do items)") and asked the user to pick one.

So the agent **did** have access to the board and all cards, but had **no way to resolve the list name "Today"** to an `id_list`, and fell back to asking the user to disambiguate.

---

## 2. Root Causes

### 2.1 Cards payload exposes only `id_list`, not list name

The read-only Trello tool `trello_list_cards(board_id)` returns, for each card:

- `id`, `name`, `url`, `closed`, **`id_list`**, `due`

There is **no `list_name`** (or equivalent) on the card. So from the tool output alone, the agent cannot know that e.g. `id_list = 5d8bc44dd0aab42f12662a18` is the "Today" list.

**Code:** `src/harle/tools/trello/tools.py` — `trello_list_cards()` builds the JSON from `TrelloCard` objects, which have `id_list: str` but no list name.  
**Client:** `src/harle/tools/trello/client.py` — `list_cards()` calls Trello API `GET /boards/{board_id}/cards` with `fields=id,name,url,closed,idList,due`. The Trello API does not include list name in the card resource by default.

### 2.2 No tool to list board lists (by name)

The Trello module currently exposes only:

- `trello_list_boards()` — boards with id, name, url, closed
- `trello_list_cards(board_id)` — cards with id_list (no list name)

There is **no** tool such as `trello_list_lists(board_id)` that returns the lists on a board with **id and name**. So the agent cannot:

1. Call "list lists for this board" and get e.g. `[{ "id": "5d8bc44d...", "name": "Today" }, ...]`
2. Map the user’s "Today" to an `id_list`
3. Filter or request cards for that list.

The Trello REST API **does** support this: **GET /1/boards/{id}/lists** returns list objects including `id` and `name`. The Harle client and tools do not call this endpoint.

### 2.3 Agent workaround: group by id_list and ask user

With only cards and `id_list`, the only thing the agent can do is group cards by `id_list` and show sample card names so the user can guess which ID is "Today". That is what happened: the agent listed several id_list values with sample cards and asked the user to pick. This is a reasonable fallback but poor UX when the user has clearly named lists (e.g. "Today") and expects the agent to use the name.

---

## 3. What needs to be implemented (options)

### 3.1 Option A — Add `trello_list_lists(board_id)` (recommended)

- **Client:** In `client.py`, add a method that calls `GET /1/boards/{board_id}/lists` with `fields=id,name` (or equivalent), and returns a list of small objects `{ id, name }`.
- **Tool:** In `tools.py`, add `trello_list_lists(board_id)` that returns JSON like:
  ```json
  { "board_id": "...", "lists": [ { "id": "...", "name": "Today" }, ... ] }
  ```
- **Agent behaviour:** When the user asks for "cards in the Today list", the agent can:
  1. `trello_list_boards()` → get board id
  2. `trello_list_lists(board_id)` → get list id for "Today"
  3. `trello_list_cards(board_id)` → filter cards where `id_list === <Today's id>`, or we add a tool that fetches cards for a list (see below).

This requires no change to the card payload and gives the agent a direct way to resolve list names to IDs.

### 3.2 Option B — Enrich card payload with list name

- **Client:** When listing cards, either:
  - Call `GET /boards/{id}/lists` once, build a map `id_list -> name`, and attach list name to each card in memory, or
  - Use Trello’s card endpoint with a parameter that includes list info (if available), or
  - Call list endpoint and merge list names into card objects.
- **Tool:** `trello_list_cards()` returns each card with e.g. `id_list` and `list_name`.
- **Agent behaviour:** The agent can filter cards by `list_name === "Today"` without an extra "list lists" call. Downside: every "list cards" call may need an extra API call to resolve list names unless we cache lists per board.

Option A is simpler (one new endpoint, no change to card response shape) and allows future tools like "list cards in list X by id or name". Option B improves the card payload for any consumer that wants to show list name.

### 3.3 Option C — Optional tool: list cards in a single list

A dedicated tool such as `trello_list_cards_in_list(board_id, list_id)` or `trello_list_cards_in_list(board_id, list_name)` could return only cards in that list. That would require either:

- Resolving `list_name` to `list_id` via `trello_list_lists()` (if we add it), or
- Accepting only `list_id` and documenting that the agent should call `trello_list_lists()` first when the user specifies a name.

Option C is complementary to Option A and improves clarity for "cards in list X" queries.

**Recommendation:** Implement **Option A** first (`trello_list_lists(board_id)`). Then the agent can resolve "Today" to an id and filter cards from `trello_list_cards()` in memory, or we can add Option C later for a single-call "cards in list" API.

---

## 4. User workaround (until implemented)

- **Tell the agent which list ID is "Today".** After the agent shows the id_list options with sample cards, reply with the correct id (e.g. "The Today list is 5d8bc44dd0aab42f12662a18"). The agent can then filter and return only cards in that list.
- **Or:** Open the board in Trello, open the "Today" list, and from the list menu or URL you can often see or derive the list ID to paste to the agent.

---

## 5. References

- **Trello tools:** `src/harle/tools/trello/tools.py` — `trello_list_boards`, `trello_list_cards` (card payload includes `id_list` only).
- **Trello client:** `src/harle/tools/trello/client.py` — `list_boards()`, `list_cards()`; no `list_lists()`.
- **Trello API — Lists:** [Trello REST API — Lists](https://developer.atlassian.com/cloud/trello/rest/api-group-lists). **GET /1/boards/{id}/lists** returns lists with `id` and `name`.
- **Manual:** `docs/manual/trello_integration_setup.md` — setup and current tool set.
