## 1. Lingua stream wiring

- [ ] 1.1 Add an aggregate `lingua.out` publish in `kaine/modules/lingua/module.py` using `self.publish` with a lightweight event containing `mode`, `text`, and metadata; verify `tests/test_lingua_module.py` still passes.
- [ ] 1.2 Replace the literal `"lingua.internal"` at line ~394 with the `INTERNAL_STREAM` constant and verify no hard-coded Lingua stream literals remain in the module.
- [ ] 1.3 Update `tests/test_config_stream_wiring.py` to include `mundus`, `perception`, `empatheia` and to treat Lingua's aggregate `lingua.out` as a real producer.

## 2. Canonical stream names

- [ ] 2.1 Add a canonical stream-constants module or extend `kaine/bus/schema.py` to export known stream names; verify `module_stream()` is used by consumers.
- [ ] 2.2 Replace hard-coded stream literals in `kaine/modules/`, `kaine/nexus/conversation.py`, `kaine/evaluation/observers/`, and `kaine/evaluation/benchmarks/` with canonical imports.
- [ ] 2.3 Add boot-time validation in `kaine/boot.py` that warns on unknown `[bus.per_stream_maxlen]` keys.
- [ ] 2.4 Extend `tests/test_stream_registry_drift.py` to assert observer stream constants match `stream_registry` outputs.

## 3. Import-boundary completeness

- [ ] 3.1 Add `kaine.preboot`, `kaine.backend_state`, `kaine.model_paths`, `kaine.organ_window_state`, `kaine.perception_preview`, and `kaine.perception_preview_server` to contract 1's `source_modules` in `pyproject.toml`.
- [ ] 3.2 Add a CI cross-check or test that verifies the setuptools `packages` list and import-linter source lists cover the same top-level packages.
- [ ] 3.3 Run `lint-imports` and verify all contracts still pass.

## 4. Ruff enforcement

- [ ] 4.1 Add a `[tool.ruff]` section to `pyproject.toml` targeting `kaine/` and `tests/` with E/W/F rules plus the currently violated rules (F821, F841, E402, E702, E741, F541).
- [ ] 4.2 Fix the ~25 outstanding ruff errors, including the missing `Callable` import in `kaine/workspace/drive_policy.py`, unused `source_map` in `prediction_error_observer.py`, unread `progressed` in `empatheia_observer.py`, and swallowed exception in `kaine/lifecycle/adapter_merge.py`.
- [ ] 4.3 Add the `ruff` pre-commit hook to `.pre-commit-config.yaml`.
- [ ] 4.4 Add a `ruff` CI job to `.github/workflows/` and verify it runs green.

## 5. Observer polling consolidation

- [ ] 5.1 Generalize `StreamSubscriberObserver` in `kaine/evaluation/_base.py` to accept `streams: tuple[str, ...]` and implement per-stream cursor tracking.
- [ ] 5.2 Add unit tests for the base class covering single-stream and multi-stream polling.
- [ ] 5.3 Remove bespoke `_run` methods from `prediction_error_observer.py`, `empatheia_observer.py`, `research_event_observer.py`, and `welfare_observer.py` and verify their tests still pass.

## 6. Validation

- [ ] 6.1 Run `openspec validate stream-wiring-quality --strict` and resolve all issues.
- [ ] 6.2 Run `ruff check kaine tests` and `lint-imports` and verify both pass.
- [ ] 6.3 Run the affected test suites and verify no regressions.
