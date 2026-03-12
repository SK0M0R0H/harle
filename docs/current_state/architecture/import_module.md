---
title: "Harle Import Module Layer — Current State"
tags: [import, current-state, architecture, vault-imports, data-migration, implementation-status]
context: global
last_updated: 2026-03-10
summary: "Tracks what the Import Module Layer implements vs the TRD, and what each missing part would unlock."
---

# Harle Import Module Layer — Current State

> This document compares the target design in the Import Module TRD with the code in `src/harle/vault_imports`. It describes what is implemented, what is partial, and what is missing, and what each missing part would unlock.

Reference TRD: [Harle Import Module Layer — Architecture & Functionality](../../trd/architecture/import_module.md)

---

## Overall Status

The Import Module Layer has **Phase 1 core infrastructure** in place: the base contract (`BaseImportSource`), data types (`ImportItem`, `ImportResult`, `ContentType`, `AccessInfo`), the Import Registry, the conversion pipeline (normalization, frontmatter, path resolution), and the Vault Writer. A dummy source exists to verify the pipeline end-to-end, and unit tests cover the registry and run_import flow. What is **not** implemented yet: real sources (Notion, Miro, bookmarks, Trello, Obsidian), the image processor (vision API), deduplication by `import_source_id`, reference-item `sync_summary` in frontmatter, source `initialize()` with the Connections Layer, CLI (`harle import ...`), Orchestrator `/import` endpoint, and config (`import_sources`, `import.image_processor`). In practice, the module is a **working framework** ready for sources and product wiring, but no user-facing import from external systems exists today.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| BaseImportSource, ImportItem, ImportResult, ContentType, AccessInfo | Implemented | `base.py`: full contract; REFERENCE and access_info supported in pipeline frontmatter. |
| Import Registry | Implemented | `registry.py`: register_source, get_source, list_sources, run_import (validate → extract → pipeline → write). ImportSourceNotFound. |
| Conversion pipeline (normalize, frontmatter, path) | Implemented | `pipeline.py`: content normalization, YAML frontmatter (incl. import_type, access_via, access_params for REFERENCE), path resolution, ConvertedItem. |
| Vault Writer | Implemented | `writer.py`: write_items, strategies skip_existing / update_changed / force, path validation, WriteResult. |
| Dummy / test source | Implemented | `dummy/source.py`: DummyImportSource, file mode, hardcoded ImportItems; used by build_import_registry(). |
| build_import_registry() | Implemented | `__init__.py`: builds registry with dummy source only; no config/connections passed to sources. |
| Unit tests | Implemented | `tests/unit/test_imports.py`: base types, pipeline, writer, registry, run_import, build_import_registry. |
| Image processor (vision API) | Not implemented | No `image_processor.py`; pipeline passes IMAGE/STRUCTURED through without processing. |
| Deduplication by import_source_id | Not implemented | Writer uses path existence + strategy only; no lookup of existing files by import_source_id. |
| sync_summary in reference frontmatter | Not implemented | Pipeline does not add row_count, last_synced, schema for reference items. |
| Source initialize() with connections | Not implemented | Registry does not call initialize(config, connections); API-mode sources cannot receive shared connections. |
| Notion source (file + API) | Not implemented | No `notion/` package (source.py, parser.py). |
| Miro source | Not implemented | No `miro/` package. |
| Bookmarks, Trello, Obsidian sources | Not implemented | Not present. |
| CLI integration | Not implemented | No `harle import` command group or Go CLI wiring. |
| Orchestrator /import endpoint | Not implemented | No HTTP endpoint for import; pipeline not exposed to product. |
| config import_sources / import | Not implemented | No `import_sources` or `import.image_processor` in config.example.yaml. |
| Post-write re-index | Not implemented | Vault Writer does not trigger Indexer sync after writing. |
| Cost estimation / --max-cost | Not implemented | No vision cost estimation or abort threshold. |

---

## What Is Implemented

### 1. Base contract and data types

`src/harle/vault_imports/base.py` implements the TRD’s core types and interface:

- **ContentType**: MARKDOWN, IMAGE, STRUCTURED, REFERENCE.
- **AccessInfo**: tool_module, params, default_filter — used for reference items.
- **ImportItem**: source_id, title, content, content_type, suggested_path, tags, context, metadata, images, access_info.
- **ImportResult**: source_name, items_found, items_imported, items_skipped, items_failed, errors, created_paths, updated_paths.
- **BaseImportSource**: name, description, initialize(), supported_modes(), validate_input(), extract(), preview(), default_config().

The contract matches the TRD; `initialize()` accepts `connections: object | None` but the registry does not call it with a ConnectionRegistry yet.

### 2. Import Registry

`registry.py` provides the central catalog and pipeline runner:

- register_source, get_source, list_sources.
- run_import(source_name, config, vault_path, dry_run): merge default config, validate_input, extract (or preview if dry_run), run_pipeline, then VaultWriter.write_items unless dry_run.
- ImportSourceNotFound when source is missing.

Validation failures are returned as ImportResult with errors; no process crash.

### 3. Conversion pipeline

`pipeline.py` converts ImportItems to vault-ready Markdown:

- Content normalization (strip, newlines).
- Frontmatter: title, tags, context, last_updated, summary, import_source, import_source_id, import_date; for REFERENCE items also import_type, access_via, access_params (from access_info). No sync_summary.
- Path resolution: suggested_path + target_dir, ensure .md extension.
- convert_item() and run_pipeline(); no image processing (comment notes “Phase 1: no image processor”).

### 4. Vault Writer

`writer.py` writes ConvertedItems to the vault:

- Validates path is under vault root.
- Creates parent directories; applies strategy (skip_existing, update_changed, force) based on file existence and content comparison.
- Returns WriteResult with created/updated/skipped/failed counts and path lists. No post-write re-index trigger.

### 5. Dummy source and registry factory

- **DummyImportSource**: file mode only, returns two hardcoded ImportItems; used to exercise the full pipeline.
- **build_import_registry(config=None)**: creates ImportRegistry and registers the dummy source; config is not passed to initialize().

### 6. Tests

`tests/unit/test_imports.py` covers base types, pipeline conversion, writer behavior, registry registration and run_import (validation failure, dry_run, actual write, config merge), and build_import_registry.

---

## What Is Only Partially Implemented

### Pipeline: no image processing or REFERENCE sync_summary

The pipeline generates correct frontmatter for REFERENCE items (import_type, access_via, access_params) but does not:

- Run any image processor for IMAGE/STRUCTURED items (they are normalized and written as-is).
- Add sync_summary (row_count, last_synced, schema) to reference frontmatter.

So reference files are structurally correct for “access via tool module” but lack the TRD’s sync metadata.

### No deduplication by import_source_id

The TRD specifies a deduplication check by import_source_id (update if content changed, skip if unchanged). The current writer only considers path existence and content diff for the same path; it does not search the vault for an existing file with matching import_source_id. Re-imports can create duplicate paths if suggested_path differs or if the same source_id was written under a different path previously.

### Source lifecycle without connections

BaseImportSource.initialize(config, connections) is never invoked by the registry. So API-mode sources have no way to receive the shared ConnectionRegistry or stored clients. The framework is ready (signature exists) but not wired.

---

## What Is Not Implemented Yet

### 1. Image processor (vision API)

Missing: `image_processor.py`, ImageProcessor.process(image_path, context_hint), and pipeline integration for IMAGE/STRUCTURED items (vision → Markdown/Mermaid). Config for model, detail, max_cost_per_run and --max-cost are also absent.

**What this would unlock:** Import of Miro boards, diagrams, and other image-heavy sources into searchable Markdown; cost-controlled vision usage.

### 2. Deduplication by import_source_id

Missing: Before writing, check vault (or index) for an existing file with the same import_source and import_source_id; update that file if content changed, skip if unchanged; avoid creating a second file for the same source entity.

**What this would unlock:** Idempotent re-imports and incremental updates without duplicate files.

### 3. sync_summary for reference items

Missing: In pipeline frontmatter for REFERENCE items, add sync_summary (e.g. row_count, last_synced, schema) so agents and users see how fresh and what shape the source data is.

**What this would unlock:** Better context for the agent and clearer “last synced” UX for reference imports.

### 4. Source initialize() with ConnectionRegistry

Missing: When building or using the registry, call source.initialize(merged_config, connection_registry) so API-mode sources can store the shared connection and use it in extract().

**What this would unlock:** Notion API, Miro API, and other API-based sources without duplicating client code; alignment with the Connections Layer described in the TRD.

### 5. Notion source (file + API)

Missing: `vault_imports/notion/` (source.py, parser.py), NotionExportParser for ZIP, NotionImportSource with file and API modes, database materialization vs reference strategy, and connection reference to notion.

**What this would unlock:** The primary migration path from Notion (ZIP export and live API) into the vault.

### 6. Miro source

Missing: `vault_imports/miro/` and MiroImportSource using the shared Miro connection, board/frame export, and image pipeline integration.

**What this would unlock:** Import of boards and diagrams from Miro with vision-generated Markdown.

### 7. Additional sources (bookmarks, Trello, Obsidian)

Missing: bookmarks (HTML), Trello (API/export), Obsidian (directory) sources.

**What this would unlock:** Broader data migration options and reuse of the same pipeline and writer.

### 8. CLI integration

Missing: `harle import` command group in the Go CLI, subcommands per source, global flags (--dry-run, --context, --target-dir, --strategy, --filter, --max-cost), and `harle import --list`.

**What this would unlock:** User-facing import from the terminal without calling the Orchestrator API directly.

### 9. Orchestrator /import endpoint

Missing: HTTP endpoint that accepts source name and config, runs the import pipeline (with registry and vault path), and streams progress.

**What this would unlock:** Remote and scripted imports, and a single backend for the CLI.

### 10. Config (import_sources, import.image_processor)

Missing: `import_sources.<source>` and `import.image_processor` (and related keys) in config.example.yaml and their use when building the registry and pipeline.

**What this would unlock:** Per-source and per-run configuration without code changes; cost and model control for vision.

### 11. Post-write re-index

Missing: After VaultWriter.write_items, trigger Indexer sync (or equivalent) so new/updated files are searchable immediately.

**What this would unlock:** Imported content available to search and context assembly right after the run.

---

## Key Deviations From The TRD

### Registry does not call initialize()

The TRD says sources are initialized once with config and connections at registration time. The current code never calls initialize(), so connections are not passed. This is a deliberate gap until the Connections Layer and config are wired.

### Deduplication is path-based only

The TRD describes deduplication by import_source_id (and optionally preserving user edits). The implementation only handles “file at this path already exists” and strategy; no cross-file lookup by import_source_id.

### Project structure: dummy instead of notion/miro

The TRD’s Phase 2/3 examples use Notion and Miro. The codebase provides a dummy source for testing the framework; real sources are to be added in line with the TRD’s “Adding a New Import Source” steps.

---

## Current Assessment

The Import Module Layer is **Phase 1 complete as a framework**: base types, registry, pipeline, and writer are in place and tested with a dummy source. The design supports full materialization and reference import (frontmatter and access_info), but no image processing, no real external sources, no CLI or API, and no config or connections wiring. The next meaningful milestones are: (1) add one real source (e.g. Notion file mode) and optionally wire initialize() and config, and (2) expose import via CLI and/or Orchestrator so users can run it.
