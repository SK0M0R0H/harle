---
title: "GitHub Setup Manual for Harle Testing"
tags: [github, ci-cd, testing, actions]
context: global
last_updated: 2026-03-04
summary: "Step-by-step GitHub-side setup for enabling Harle testing workflows, protections, and secrets."
---

# GitHub Setup Manual for Harle Testing

This manual explains how to configure the **GitHub repository side** so the testing strategy from `docs/trd/testing_strategy.md` can run safely and consistently.

## 1) Enable GitHub Actions in the repository

1. Open **Settings → Actions → General**.
2. Set **Actions permissions** to: `Allow all actions and reusable workflows`.
3. Under **Workflow permissions**, enable:
   - `Read and write permissions`
   - `Allow GitHub Actions to create and approve pull requests` (optional but useful for future automation).

> Why: the CI/CD plan relies on push/PR/nightly workflows and optional automation tasks.

## 2) Add required secrets

Open **Settings → Secrets and variables → Actions → New repository secret** and add:

- `OPENAI_API_KEY` (semantic eval + live E2E)
- `TRELLO_API_KEY` (live E2E for Trello module)
- `TRELLO_API_TOKEN` (live E2E for Trello module)
- `TAVILY_API_KEY` (live E2E for web search module)
- `CODECOV_TOKEN` (coverage upload)

### Optional: environment-scoped secrets

For stricter control, create environments:

- `ci` for push/PR checks
- `nightly` for scheduled checks
- `release` for pre-release/live checks

Then move production-sensitive secrets (for example `OPENAI_API_KEY`) to `nightly`/`release` only.

## 3) Configure branch protection for `main`

Open **Settings → Branches → Add branch protection rule** for `main`.

Recommended settings:

- ✅ Require a pull request before merging
- ✅ Require approvals (at least 1)
- ✅ Require status checks to pass before merging
- ✅ Require branches to be up to date before merging
- ✅ Do not allow bypassing the above settings

Add these checks as required once workflows exist:

- `lint`
- `test-unit`
- `test-integration` (PRs)
- `coverage` (PRs)
- `test-cli`

## 4) Use the workflow files in this repository

This repository now includes workflow files under `.github/workflows/` aligned with the testing strategy:

- `ci.yml` for push/PR jobs:
  - lint/type checks (`ruff`, `mypy`)
  - unit tests
  - integration tests on PR
  - coverage + Codecov upload
- `nightly.yml` for scheduled jobs:
  - emulated E2E tests
  - dependency audit (`pip-audit`)

## 5) Configure Codecov (recommended)

1. Install/authorize Codecov for the repository.
2. Ensure `CODECOV_TOKEN` is present in repository secrets.
3. In Codecov settings, enable PR comments and status checks.
4. Set target coverage policy (initial recommendation from strategy: fail under 70% in CI).

## 6) Validate end-to-end GitHub setup

After these workflow files are on your default branch, verify in **Actions** tab:

1. Push to a feature branch → `CI` workflow starts.
2. Open PR to `main` → PR jobs run, including integration/coverage.
3. Trigger `Nightly` manually (`workflow_dispatch`) to validate schedule workflow.
4. Confirm required checks block merge when failing.

## 7) Operating model (recommended)

- **Every push:** lint + unit tests + security scan.
- **Every PR to `main`:** all push checks + integration + coverage gate.
- **Nightly:** emulated E2E + dependency audit.
- **Pre-release/manual:** full E2E with live dependencies and release build steps.

This cadence matches the four-layer testing model and keeps fast feedback on PRs while reserving expensive checks for nightly/release windows.
