---
title: "Investigation — Trello Card Labels Not Returned (Labels Omitted from Request)"
tags: [investigation, trello, tools, labels, cards, api-fields]
context: global
last_updated: 2026-03-13
summary: "Documents why the agent reports no labels on cards: the Trello client requests only a subset of card fields and omits idLabels/labels; root cause and fix."
---

# Investigation: Trello Card Labels Not Returned — Agent Reports No Labels on Cards

**Date:** 2026-03-13

**Goal of this file:** Use during implementation to understand why the agent sees no tags/labels on Trello cards and what to change so card labels are included in the tool response.

**Related:** [2026-03-13_trello_list_by_name.md](./2026-03-13_trello_list_by_name.md) — same tool (`trello_list_cards`) and board/card flow; that investigation covers list names, this one covers labels.

---

## 1. Problem

User has **labels** (tags) on cards in their Trello board (e.g. in the "Today" list). When the user asked the agent about labels on those cards, the agent reported that card objects contain **no labels array or label fields**.

**Expected behaviour:** Cards returned by the Trello tool include label information (e.g. label IDs and/or names/colors) so the agent can report or filter by labels.

**Actual behaviour:** The agent fetched all cards for the board via `trello_list_cards(board_id)` and filtered to the Today list. The card objects in the response include only `id`, `name`, `url`, `id_list`, and `due` — **no labels**. The agent correctly concluded from the payload that there are no label fields and reported that to the user.

Example agent reply (summary):

- "I found no tags/labels on any cards in the Today list. The Trello card objects returned for that list contain no labels array or label fields."
- "The card objects include id, name, url, id_list and due but no labels."

So the **Trello API can provide labels**, but the Harle Trello tool **does not request or return them**.

---

## 2. Root Cause

### 2.1 Card request asks only a subset of fields (no labels)

The Trello client requests cards with an explicit **`fields`** parameter, which limits the API response to only those fields. Labels are never requested.

**Code:** `src/harle/tools/trello/client.py` — `list_cards()`:

```python
data = await self._get_json(
    f"/boards/{board_id}/cards",
    params={"fields": "id,name,url,closed,idList,due"},
)
```

So the request explicitly asks for: `id`, `name`, `url`, `closed`, `idList`, `due`. It does **not** include:

- **`idLabels`** — array of label IDs attached to the card
- **`labels`** — (when requested) full label objects (id, name, color, etc.)

Because these are omitted from `fields`, the Trello API does not return them, so the client never sees label data.

### 2.2 Internal model and tool output have no label fields

- **TrelloCard** (`client.py`): The dataclass has `id`, `name`, `url`, `closed`, `id_list`, `due`. There is no `id_labels` or `labels` field, so even if the API returned them, the current code would not map them into the internal model.
- **trello_list_cards** (`tools.py`): The JSON built for each card includes only `id`, `name`, `url`, `closed`, `id_list`, `due`. No label field is serialized.

So the fix requires: (1) adding label fields to the API request, (2) adding label fields to `TrelloCard` and the mapping in `list_cards()`, and (3) adding label fields to the tool’s JSON output.

---

## 3. Trello API behaviour (for implementation)

The Trello REST API supports label-related fields on card objects:

- **`idLabels`** — Array of label IDs on the card. Lightweight; always available when requested in `fields`.
- **`labels`** — Full label objects (id, name, color, etc.). Typically requested as a **nested resource** (e.g. via a query parameter or a separate convention), not always as a single card field — check the current [Trello REST API card and labels documentation](https://developer.atlassian.com/cloud/trello/rest/api-group-cards/) for the exact way to request `labels` on board cards.

**Recommendation:** Start by adding **`idLabels`** to the `fields` parameter. That gives the agent at least label IDs per card. Optionally, add full label details (name, color) either by including `labels` in the card response if the API supports it in one call, or by resolving label IDs to names/colors (e.g. via board labels or GET /labels/{id}) if needed for UX.

---

## 4. What needs to be implemented

1. **Client (`client.py`)**
   - Add `idLabels` (and optionally `labels`) to the `fields` param in the `/boards/{board_id}/cards` request.
   - Extend **TrelloCard** with a field such as `id_labels: list[str]` (and optionally `labels: list[dict]` or a small `TrelloLabel` dataclass).
   - In `list_cards()`, map the API’s `idLabels` (and if used, `labels`) from each card item into the TrelloCard instances.

2. **Tool (`tools.py`)**
   - In `trello_list_cards()`, include in each card’s JSON at least `id_labels` (list of label IDs). Optionally include a `labels` array with `id`, `name`, `color` (or similar) per label for human-readable answers.
   - Update the docstring so it states that cards include label information (e.g. `id_labels` and optionally `labels`).

3. **Tests**
   - Unit tests for the Trello module should cover cards with and without labels: assert that label IDs (and optionally label names/colors) appear in the tool output when the API returns them.

---

## 5. User workaround (until implemented)

There is no workaround on the agent side: the tool does not expose label data. The user can:

- Open cards in Trello in the browser to see labels, or
- Wait until the tool is extended to request and return `idLabels` (and optionally full labels).

---

## 6. References

- **Trello client (card request and model):** `src/harle/tools/trello/client.py` — `list_cards()`, `TrelloCard`; `fields` param and dataclass definition.
- **Trello tool (card JSON):** `src/harle/tools/trello/tools.py` — `trello_list_cards()`, card dict construction.
- **Trello API — Cards:** [Trello REST API — Cards](https://developer.atlassian.com/cloud/trello/rest/api-group-cards/) — card object and query params.
- **Trello API — Labels:** [Trello REST API — Labels](https://developer.atlassian.com/cloud/trello/rest/api-group-labels/) — label object and endpoints.
- **Related investigation:** [2026-03-13_trello_list_by_name.md](./2026-03-13_trello_list_by_name.md) — list names not returned (same `trello_list_cards` flow).
