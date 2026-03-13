---
title: "Trello Integration in Harle — User Expectations & LLM Tool Definition"
tags: [research, trello, tools, integration, user-expectations, llm-tools, product]
context: global
last_updated: 2026-03-13
summary: "Product research on how users expect to use Trello in Harle; synthesizes investigations, manual, and external research to recommend which tools to expose to the LLM."
---

# Trello Integration in Harle — User Expectations & LLM Tool Definition

> This document captures product research on how users would use Trello integration in Harle. It combines project investigations, the current setup manual, and external research to make explicit which tools should be defined for the LLM and in what order of priority.

**Audience:** Product and implementation. Use this when extending the Trello tool module or deciding read vs write capabilities.

**Related:** [Trello Integration Setup Manual](../manual/trello_integration_setup.md), [Investigation — List by name](../investigations/2026-03-13_trello_list_by_name.md), [Investigation — Cards missing labels](../investigations/2026-03-13_trello_cards_missing_labels.md), [Tool Module Architecture](tool_module_architecture.md), [TRD Tools](../trd/architecture/tools.md).

---

## 1. Current state in Harle

Harle’s Trello module is **read-only** and exposes two tools:

| Tool | Purpose | Limitation (from investigations) |
|------|---------|-----------------------------------|
| `trello_list_boards` | List boards (id, name, url, closed) | None identified. |
| `trello_list_cards(board_id)` | List all cards on a board | Cards have `id_list` only (no list **name**); no **labels** on cards. |

The agent is guided by the built-in skill `read_sequence.md`: list boards → pick board → list cards. There is **no** way for the agent to resolve a list by **name** (e.g. “Today”) or to see or filter by **labels**, which directly blocks natural requests like “What’s in my Today list?” or “Which cards have the Urgent label?”.

---

## 2. How users expect to use Trello with an AI assistant

Findings from project investigations and external research are aligned: users expect to use Trello via **natural language** for both **reading** and **acting** on boards, with a strong emphasis on **named lists**, **labels**, and **status/overdue** awareness.

### 2.1 Read-oriented expectations (query / status)

- **“What’s on my board?” / “What’s in my Today list?”**  
  Users refer to lists by **name** (e.g. “Today”, “In Progress”, “Done”). They do not think in opaque list IDs. The agent must be able to resolve list names to IDs and return cards for that list.

- **“What’s overdue?” / “What’s due this week?”**  
  Requires cards to expose **due** (already in the client); the agent can filter. Optional: support filtering by list and/or label in the same mental model.

- **“Which cards have label X?” / “Show me high-priority items.”**  
  Users use **labels** (tags, colors, names) for priority, type, or status. Cards must expose label information (at least IDs; ideally id + name + color) so the agent can report or filter by label.

- **“Summarize In Progress” / “Status of project X.”**  
  Same as above: list-by-name + cards with list name and labels allow the agent to summarize by list or label. Natural-language board querying (e.g. n8n + GPT, Voiact, Tars) is a common pattern: “query your board in natural language.”

- **Daily standups / quick status.**  
  Use cases (e.g. Steady, Fellow) show that surfacing “what’s in this list” and “what changed” is central. Read-only tools that return list names and labels are sufficient for “what’s on my board / in Today / In Progress.”

### 2.2 Write-oriented expectations (create / update)

- **“Create a card for X” / “Add a task: …”**  
  Creating cards from conversation (e.g. from support chats, meeting notes, or ad-hoc requests) is a standard integration pattern (OpenAssistantGPT, Tars, Guru, Fellow). Users expect to say what the task is and optionally which list or board.

- **“Move card X to Done” / “Put this in In Progress.”**  
  Moving cards between lists by **list name** is a core Kanban action. The agent needs list name → ID resolution and a move operation.

- **“Add label Urgent” / “Tag this as bug.”**  
  Adding (or removing) labels on cards is commonly expected in bug tracking, prioritization, and triage workflows.

- **“Add a comment” / “Log that we’re waiting on design.”**  
  Comments on cards are used for updates and handoffs. Many integrations (e.g. customer support → Trello) add context as comments.

- **Assignees, checklists, due dates.**  
  Often mentioned in “AI + Trello” use cases (e.g. create card with description, due date, checklist). Lower priority than “create / move / label” for a first write phase but part of user expectations.

### 2.3 Approval and safety

Industry pattern (LangChain, Microsoft Agent Framework, Oracle AI Agent docs): **read** operations (list, get, search) do not require human approval; **write** operations (create, update, move, delete, add comment/label) should be gated by **human-in-the-loop** approval. Harle’s TRD already specifies this: read tools `requires_approval = False`, write tools `requires_approval = True`. Trello write tools should follow that pattern.

---

## 3. Gaps identified in project investigations

The two investigation documents explain exactly what is missing for **read** flows:

1. **List names**  
   Cards only have `id_list`. There is no `trello_list_lists(board_id)` and no `list_name` on cards, so the agent cannot map “Today” to an id.  
   **Fix (recommended):** Add `trello_list_lists(board_id)` returning `[{ "id", "name" }, ...]`. Optionally enrich card payload with `list_name` (e.g. by resolving id_list against lists).

2. **Labels on cards**  
   The client requests only `id,name,url,closed,idList,due` and does not request `idLabels` (or `labels`). The tool output therefore has no label data.  
   **Fix:** Add `idLabels` (and optionally full label details) to the API request and to the card model and tool output.

Implementing these two fixes makes the **existing** two tools sufficient for the main read expectations (list by name, filter by label, “what’s overdue”) without adding more read tools. Optionally, a dedicated **list cards in list** tool (by list_id or list_name) can reduce agent steps and clarify intent.

---

## 4. Recommended tools for the LLM

Below is the recommended tool set, ordered by priority and grouped by read vs write. The list is the single source for “which tools should be defined for the LLM.”

### 4.1 Read tools (no approval)

| Priority | Tool | Description | Status / note |
|----------|------|-------------|----------------|
| 1 | `trello_list_boards` | List boards (id, name, url, closed). | **Exists.** |
| 2 | `trello_list_lists(board_id)` | List lists on a board (id, name). | **Add.** Required so the agent can resolve “Today” / “In Progress” to an id. |
| 3 | `trello_list_cards(board_id)` | List cards on a board. | **Exists; enrich.** Add `id_labels` (and optionally `labels` with id/name/color) and, if feasible, `list_name` per card so the agent can filter by list name and label without extra calls. |
| 4 | (Optional) `trello_list_cards_in_list(board_id, list_id_or_name)` | Cards in a single list. | **Optional.** Convenience: one call for “cards in Today.” Can resolve name → id via `trello_list_lists` or accept name and resolve inside the tool. |

No other read tools are strictly necessary for the described expectations; search/filter can be done in-memory by the agent from boards + lists + cards.

### 4.2 Write tools (with approval)

All write tools should use `permission = "write"` and `requires_approval = True` (or equivalent in Harle’s registry).

| Priority | Tool | Description | Note |
|----------|------|-------------|------|
| 1 | `trello_create_card(list_id, name, description?, due?)` | Create a card on a list. | Core expectation: “add a task.” Optional: description, due. |
| 2 | `trello_move_card(card_id, list_id)` | Move a card to another list. | “Move to Done” / “Put in In Progress.” List id can come from `trello_list_lists`. |
| 3 | `trello_add_label_to_card(card_id, label_id)` or `(card_id, label_name)` | Add a label to a card. | “Tag as Urgent.” May require resolving label name → id (board labels or GET label). |
| 4 | `trello_add_comment_to_card(card_id, text)` | Add a comment to a card. | “Log that we’re blocked on X.” |
| 5 | (Later) | Update card (title, description, due), remove label, assign member, add checklist item. | Lower priority; can be added when needed. |

Implement in the order above so that the agent can first **create** and **move** cards, then **label** and **comment**, which covers the main conversational use cases.

### 4.3 Tool summary for implementation

- **Define for LLM (read):**  
  `trello_list_boards`, `trello_list_lists`, `trello_list_cards` (enriched). Optionally `trello_list_cards_in_list`.

- **Define for LLM (write):**  
  `trello_create_card`, `trello_move_card`, `trello_add_label_to_card`, `trello_add_comment_to_card`.

- **Enrich existing:**  
  `trello_list_cards` → include list names and label info so the agent can answer “what’s in Today?” and “which have label X?” without guessing list IDs or seeing empty labels.

---

## 5. Skills and docstrings

- **Read sequence:** Update `read_sequence.md` to: (1) list boards, (2) list lists for the chosen board, (3) list cards (and optionally list cards in list by name). State that cards include `list_name` and `id_labels`/`labels`.
- **Write flow:** When write tools exist, add a skill (e.g. `write_sequence.md` or a combined skill) that tells the agent to use `trello_list_lists` to resolve list names before create/move, and to use approval for any write.
- **Tool docstrings:** Each tool’s docstring is what the LLM sees. Clearly document parameters (e.g. `list_id` vs `list_name` if both are supported), return shape (especially that cards include labels and list_name), and that list names can be resolved via `trello_list_lists`.

---

## 6. References

### Project

- [Trello Integration Setup Manual](../manual/trello_integration_setup.md) — current tools and credentials.
- [Investigation — Trello list by name](../investigations/2026-03-13_trello_list_by_name.md) — why “Today” cannot be resolved; recommendation for `trello_list_lists`.
- [Investigation — Trello cards missing labels](../investigations/2026-03-13_trello_cards_missing_labels.md) — why labels are missing; fields and client/tool changes.
- `src/harle/tools/trello/` — client, tools, module, read_sequence skill.
- [TRD — Tools](../trd/architecture/tools.md) — permission model, approval, module layout.

### External (research)

- Trello REST API: [Cards](https://developer.atlassian.com/cloud/trello/rest/api-group-cards/), [Lists](https://developer.atlassian.com/cloud/trello/rest/api-group-lists/), [Labels](https://developer.atlassian.com/cloud/trello/rest/api-group-labels/).
- AI + Trello: Tars Trello integration (read/write, create from chat); Guru Trello AI agent (create, move, search); OpenAssistantGPT (create cards from conversation); Voiact (conversation → cards, bulk ops); n8n “Query Trello with natural language”; Steady (standups + Trello); Fellow (meeting notes → Trello).
- Human-in-the-loop: LangChain Deep Agents (`interrupt_on`), Microsoft Agent Framework (`approval_mode`), Oracle AI Agent — read vs write approval patterns for project management tools.
