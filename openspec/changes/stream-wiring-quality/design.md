## Context

See `proposal.md` for motivation. Lingua already defines `EXTERNAL_STREAM` and `INTERNAL_STREAM` but bypasses `self.publish`, so the registry-derived `lingua.out` is never written. Stream literals are scattered across modules, Nexus, evaluation, and config. The import-linter contract list in `pyproject.toml` omits newer top-level modules. Ruff is not configured or run anywhere.

## Goals / Non-Goals

**Goals:**
- Make Lingua's events visible to the cycle engine through a consistent stream contract.
- Eliminate hard-coded stream literals outside the canonical source.
- Complete the sidecar-boundary source list.
- Turn on ruff in pre-commit and CI and clear existing errors.
- Consolidate duplicated observer polling loops.

**Non-Goals:**
- Changing the module architecture beyond the stream contract.
- Adding new modules or capabilities.
- Rewriting the evaluation observers' business logic.

## Decisions

**Decision 1: Add an aggregate `lingua.out` stream.**
Lingua will continue to publish to `lingua.external` and `lingua.internal` for their specific consumers, and will also call `self.publish` with a lightweight aggregate event on `lingua.out` containing mode, text, and metadata. This preserves the existing `<module>.out` convention that the engine and other consumers expect, without breaking the separate-channel design.
- *Alternative:* Update the engine/registry to read `lingua.external`/`lingua.internal`. Rejected because it spreads Lingua-specific knowledge into the generic registry and breaks the `<module>.out` abstraction for every other module.

**Decision 2: Export canonical stream constants from `kaine.bus.schema`.**
Add a small registry of known module streams (or make `module_stream()` the single helper) and update consumers to import from there. Config validation will warn on unknown `[bus.per_stream_maxlen]` keys.

**Decision 3: Add missing modules to the import-linter source list.**
Add `kaine.preboot`, `kaine.backend_state`, `kaine.model_paths`, `kaine.organ_window_state`, `kaine.perception_preview`, and `kaine.perception_preview_server` to contract 1's `source_modules`. Also add a CI cross-check that the setuptools `packages` list and the import-linter source lists stay in sync.

**Decision 4: Configure ruff with a conservative rule set.**
Enable the error rules that are already violated (F821, F841, E402, E702, E741, F541) plus the standard E/W/F set. Fix the ~25 existing violations. Add the ruff pre-commit hook and a GitHub Actions job.

**Decision 5: Generalize `StreamSubscriberObserver` to multi-stream.**
Change the base class to accept `streams: tuple[str, ...]`, keep per-stream cursors, and remove the custom `_run` methods from the four multi-stream observers.

## Risks / Trade-offs

- **[Risk]** Adding `lingua.out` changes the bus traffic shape.
  → **Mitigation:** The aggregate event is small (mode, text, metadata); it does not duplicate the full internal/external payloads.
- **[Risk]** Ruff enforcement blocks unrelated future changes.
  → **Mitigation:** The initial rule set is conservative and focused on real errors; it can be expanded later.
- **[Risk]** Removing observer `_run` methods introduces regressions.
  → **Mitigation:** The base-class loop will be tested with both single- and multi-stream configurations before the custom methods are removed.
