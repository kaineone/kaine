## Why

The codebase has several related wiring and quality problems: Lingua publishes to `lingua.external` and `lingua.internal` but the cycle engine reads a phantom `lingua.out`; stream names are duplicated as raw string literals across modules, Nexus, evaluation, and config; the import-boundary contract that protects the evaluation sidecar omits several top-level modules; and ruff linting is advertised but entirely unenforced. This change cleans up the stream contract, completes the boundary guard, and turns on the lint gate.

## What Changes

- **Reconcile Lingua's bus streams with the engine and evaluation.** Either have Lingua emit an aggregate `lingua.out` stream that the engine reads, or centralize stream derivation so all consumers know Lingua's real streams are `lingua.external` and `lingua.internal`. Update `tests/test_config_stream_wiring.py` to match.
- **Canonicalize stream names.** Introduce shared constants or derive consumer streams via `kaine.bus.schema.module_stream()` everywhere, and extend the drift test to catch hard-coded literals.
- **Complete the import-boundary contract list.** Add the missing top-level modules (`kaine.preboot`, `kaine.backend_state`, `kaine.model_paths`, `kaine.organ_window_state`, `kaine.perception_preview`, `kaine.perception_preview_server`) to the sidecar-boundary source list in `pyproject.toml`.
- **Enforce ruff in pre-commit and CI.** Add a `[tool.ruff]` section to `pyproject.toml`, add the `ruff` pre-commit hook, add a CI job, and clear the ~25 outstanding lint errors.
- **Remove duplicated polling loops in evaluation observers.** Generalize `StreamSubscriberObserver` to handle multi-stream observers and delete the bespoke `_run` reimplementations.

## Capabilities

### New Capabilities
- `stream-contract`: Canonical stream names and validation across modules, Nexus, and evaluation.

### Modified Capabilities
- `lingua`: Clarify the module's output streams and their consumers.
- `event-bus`: Add canonical stream-name derivation and drift detection.
- `architecture-boundaries`: Complete the sidecar-boundary source list and add a cross-check against the setuptools package list.
- `evaluation-observers`: Consolidate the observer polling loop on the shared base class.

## Impact

- `kaine/modules/lingua/module.py`, `kaine/bus/schema.py`, `kaine/cycle/engine.py`, `kaine/modules/registry.py`.
- `kaine/evaluation/stream_registry.py`, `kaine/evaluation/observers/*.py`.
- `kaine/nexus/conversation.py` and other consumers of stream literals.
- `config/kaine.toml` stream references.
- `pyproject.toml` (`[tool.ruff]`, `[tool.setuptools] packages`, import-linter contracts).
- `.pre-commit-config.yaml` and `.github/workflows/*.yml`.
- `tests/test_stream_registry_drift.py`, `tests/test_config_stream_wiring.py`, `tests/test_import_boundary_contracts.py`.
