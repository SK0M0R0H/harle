---
title: "Trello Integration Setup Manual"
tags: [trello, manual, setup, integration, tools, api-credentials]
context: global
last_updated: 2026-03-13
summary: "Step-by-step setup for Harle Trello integration: obtaining API key and token, configuring credentials, and verifying tools."
---

# Trello Integration Setup Manual

This manual explains how to enable **Trello** in Harle so the agent can list boards and cards via the read-only Trello tools (`trello_list_boards`, `trello_list_cards`).

## 1) Obtain Trello API key and token

Harle uses Trello’s REST API with **API key** + **token** authentication. You need both.

### API key

1. Go to [Trello Power-Ups admin](https://trello.com/power-ups/admin).
2. Open your Power-Up (or create one for “Harle” if needed).
3. Open the **API Key** tab.
4. Click **Generate a new API Key** and copy the key.

Alternatively, for a legacy app key: [https://trello.com/app-key](https://trello.com/app-key).

### Token

1. In the same Power-Up’s **API Key** tab, use the **Token** link next to your API key.
2. You’ll be sent to Trello’s authorization page. Choose scope and expiration.
3. Click **Allow** and copy the generated token.

**Security:** Treat the token like a password. The API key can be shared; the token must stay secret. If the token is exposed, revoke it in Trello and generate a new one.

## 2) Configure credentials in Harle

Harle enables the Trello tool module only when **both** `TRELLO_API_KEY` and `TRELLO_API_TOKEN` are set. Credentials are read from the **environment** (not from `config.yaml` in the current setup).

### Option A: Environment variables (recommended)

Set these before starting the Harle server (e.g. in your shell or process manager):

```bash
export TRELLO_API_KEY="your-api-key"
export TRELLO_API_TOKEN="your-api-token"
```

Then start Harle as usual. The tool factory will register the Trello connection and the Trello module.

### Option B: `.env` or similar

If you use a `.env` file in the project root (or set `HARLE_DOTENV_PATH`), Harle loads it automatically at startup. Add:

```
TRELLO_API_KEY=your-api-key
TRELLO_API_TOKEN=your-api-token
```

Do **not** commit this file; keep it in `.gitignore`.

## 3) What gets enabled

When both variables are set:

- A **Trello connection** is registered with the shared connection registry (used by the Trello tool module).
- The **Trello tool module** is registered and exposes:
  - **`trello_list_boards`** — lists boards visible to the authenticated member (id, name, url, closed).
  - **`trello_list_cards`** — lists cards for a given board (id, name, url, closed, id_list, due).
- The built-in skill **read_sequence** is available so the agent is guided to use a read-first flow: list boards, then list cards for the chosen board.

All Trello tools are **read-only** and do not require approval by default.

## 4) Verifying the setup

1. **Start the Harle server** with the environment variables set. In the logs you should see:
   - `Connection registered: trello`
   - `Tool registry ready: … trello_list_boards, trello_list_cards …` (or similar, depending on other modules).

2. **Use the API or CLI** with a prompt that implies Trello (e.g. “List my Trello boards” or “What’s on my Work board?”). The agent should be able to call `trello_list_boards` and, if you have boards, `trello_list_cards` with the relevant board ID.

3. **If something fails:**
   - **Missing credentials:** Ensure both `TRELLO_API_KEY` and `TRELLO_API_TOKEN` are set in the environment of the process that runs Harle.
   - **Invalid credentials:** Trello API will return errors (e.g. 401). Double-check the key and token; regenerate the token if needed.
   - **Empty or wrong board:** `trello_list_cards` requires a valid board ID from `trello_list_boards`; the agent should call boards first, then cards.

A future **`harle connections status`** command (see `docs/trd/architecture/connections.md`) will provide a single place to check Trello (and other connections) health; until then, startup logs and a test request are the main verification.

## 5) CI / automation (e.g. GitHub Actions)

For automated or CI runs that use Trello (e.g. live E2E tests), add the same variables as **secrets** in your CI environment and pass them into the Harle process. Example for GitHub Actions: add repository secrets `TRELLO_API_KEY` and `TRELLO_API_TOKEN` and reference them in the workflow (see `docs/manual/github_setup_testing.md` for the pattern).

## Summary

| Step | Action |
|------|--------|
| 1 | Get **API key** and **token** from Trello (Power-Ups admin or app-key page). |
| 2 | Set **`TRELLO_API_KEY`** and **`TRELLO_API_TOKEN`** in the environment. |
| 3 | Start Harle; confirm “Connection registered: trello” and Trello tools in the registry. |
| 4 | Verify with a prompt that uses Trello; fix credentials or token if you see API errors. |

For architecture and connection design, see `docs/trd/architecture/connections.md` and `docs/trd/architecture/tools.md`.
