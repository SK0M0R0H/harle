# Agent prompt seeds (bootstrap + tests)

Markdown files here are the **single source of truth** for default role prompts under `prompts/` when seeding a vault (`/init`, `harle-init`) and for E2E tests (copied into the temporary dataset).

Edit these files to change shipped defaults. Filenames must be `{role}.md` for each known orchestrator role.

Other default vault Markdown (policies, examples, knowledge) lives in `../vault_seeds/` with the same paths as under a vault root.
