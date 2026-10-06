## 1. Lingua stream wiring

- [x] 1.1 Add an aggregate `lingua.out` publish in `kaine/modules/lingua/module.py` using `self.publish` with a lightweight event containing `mode`, `text`, and metadata; verify `tests/test_lingua_module.py` still passes.
- [x] 1.2 Replace the literal `"lingua.internal"` at line ~394 with the `INTERNAL_STREAM` constant and verify no hard-coded Lingua stream literals remain in the module.
- [x] 1.3 Update `tests/test_config_stream_wiring.py` to include `mundus`, `perception`, `empatheia` and to treat Lingua's aggregate `lingua.out` as a real producer.

## 2. Canonical stream names

- [x] 2.1 Add a canonical stream-constants module or extend `kaine/bus/schema.py` to export known stream names; verify `module_stream()` is used by consumers.
- [ ] 2.2 Replace hard-coded stream literals in `kaine/modules/`, `kaine/nexus/conversation.py`, `kaine/evaluation/observers/`, and `kaine/evaluation/benchmarks/` with canonical imports.
- [x] 2.3 Warn at boot on unknown `[bus.per_stream_maxlen]` keys. `kaine/boot.py` no longer exists; the warning lives in the preflight bus budget (`kaine/preboot.py`), which every boot runs.
- [x] 2.4 Extend `tests/test_stream_registry_drift.py`: every diagnostics stream from `stream_registry` is a known stream, and `MODULE_STREAMS` is exactly one stream per declared module. The observers still define their own stream literals, so checking those constants against the registry is part of 2.2, when they import the canonical names.

## 3. Import-boundary completeness

- [x] 3.1 Add `kaine.preboot`, `kaine.backend_state`, `kaine.model_paths`, `kaine.organ_window_state`, `kaine.perception_preview`, and `kaine.perception_preview_server` to contract 1's `source_modules` in `pyproject.toml`.
- [x] 3.2 Add a test that every top-level `kaine` module and package is classified by an import contract (`tests/test_import_contract_coverage.py`). Setuptools now ships every `kaine*` package through `packages.find`, so there is no package list left to compare against.
- [x] 3.3 Run `lint-imports` and verify all contracts still pass.

## 4. Ruff enforcement

- [x] 4.1 Add a `[tool.ruff]` section to `pyproject.toml` targeting `kaine/` and `tests/` with E/W/F rules plus the currently violated rules (F821, F841, E402, E702, E741, F541).
- [x] 4.2 Fix the ~25 outstanding ruff errors, including the missing `Callable` import in `kaine/workspace/drive_policy.py`, unused `source_map` in `prediction_error_observer.py`, unread `progressed` in `empatheia_observer.py`, and swallowed exception in `kaine/lifecycle/adapter_merge.py`.
- [x] 4.3 Add the `ruff` pre-commit hook to `.pre-commit-config.yaml`.
- [x] 4.4 Add a `ruff` CI job to `.github/workflows/` and verify it runs green.

## 5. Observer polling consolidation

- [x] 5.1 Generalize `StreamSubscriberObserver` in `kaine/evaluation/_base.py` to accept `streams: tuple[str, ...]` and implement per-stream cursor tracking.
- [x] 5.2 Add unit tests for the base class covering single-stream and multi-stream polling.
- [x] 5.3 Remove bespoke `_run` methods from `prediction_error_observer.py`, `empatheia_observer.py`, `research_event_observer.py`, and `welfare_observer.py` and verify their tests still pass.

## 6. Validation

- [x] 6.1 Run `openspec validate stream-wiring-quality --strict` and resolve all issues.
- [x] 6.2 Run `ruff check kaine tests` and `lint-imports` and verify both pass.
- [ ] 6.3 Run the affected test suites and verify no regressions.

## Review status (2026-09-22)

Tasks 1.2, 1.3, 2.1, 2.3, 2.4, 3.2 and 5.2 are now done. Task 2.2 (replacing stream literals across module and observer files) is deliberately left open and sequenced after the in-flight module PRs, to avoid merge conflicts. Task 6.3 (running the affected test suites) remains open until those PRs land and the full suite can be exercised.
