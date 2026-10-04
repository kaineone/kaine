# Code boundaries

This page explains the package-level boundaries that keep KAINE's cognitive runtime, research instrumentation, plugins, and operator UI separate. Read it before you move code across packages, and when you need to know why the entity can run without the research sidecar. For the broader system picture, see [Architecture](./README.md).

## The sidecar boundary

`kaine/evaluation/` is the observe-only research subsystem. It holds the sidecar observers, A/B divergence tracking, the red-team harness, and benchmarks. It reads the bus and module state; it never injects signals back into the cognitive loop. The individuation producer lives in the cycle under `kaine/cycle/` and writes encrypted welfare evidence to `state/individuation/`.

Core code never imports `kaine.evaluation/`. The entity must be able to boot and run a full cognitive life with the entire `kaine/evaluation/` directory deleted. If core code reached into evaluation, disabling research would break the entity, and the "instrumentation is observe-only" guarantee would be false.

### The two composition roots

Only two entrypoints are allowed to wire the sidecar in:

| Seam | Role |
|------|------|
| `kaine/cycle/__main__.py` | Boots the cognitive cycle and constructs the sidecar registry if evaluation is enabled. |
| `kaine/nexus/__main__.py` | Boots the operator UI process and surfaces sidecar output. |

These are entrypoints, not library code. Nothing else imports them. The dependency points one way — entrypoint → both halves — and never core → evaluation.

### Cross-cutting primitives

When core code needs logic that lives in evaluation, do not import it. Move the primitive to a boundary-neutral home instead. That keeps both sides able to share the helper without either side owning the other.

## Boundary-neutral shared homes

Boundary-neutral homes sit between core and evaluation. They may import neither the core runtime (`kaine/cycle/`, `kaine/modules/`, `kaine/nexus/`, `kaine/workspace/`) nor `kaine/evaluation/`. The contract in [`pyproject.toml`](../../pyproject.toml) lists ten neutral homes; the most used are:

| Home | Contents |
|------|----------|
| `kaine/persistence/` | `AsyncJsonlSink` and persistence primitives. |
| `kaine/experiment/` | Experiment helpers, e.g. `welfare_counts`. |
| `kaine/privacy_filter.py` | `PrivacyFilter` — content redaction. |
| `kaine/text_embedding.py` | The text embedder. |
| `kaine/lifecycle/welfare_signal.py` | The sustained-distress detector. |

The contract also includes `kaine/state_io.py`, `kaine/storage.py`, `kaine/shared_services.py`, `kaine/net.py`, and `kaine/memory_kinds.py`. See [`pyproject.toml`](../../pyproject.toml) under `[tool.importlinter]` for the current definitions.

## Declared layering

The import contracts document and enforce the project's real layering. Violations break CI.

### Modules and the cycle

The domain organs in `kaine/modules/` are leaf components driven by the cycle. They must not import the cycle runtime: the engine/loop, registry, preflight, boot, `__main__`, the Spot supervisor, or the preservation/research monitors. See [The modules](../09-modules/README.md) for what each module does.

The one allowed dependency is the pure data/contract module `kaine.cycle.types` (`WorkspaceSnapshot`). That import is permitted directly and transitively — for example, through neutral collaborators like `kaine.faithful` and `kaine.workspace.volition`. It is the single declared exception to "modules stay independent of the cycle."

### Workspace and cognitive modules

`kaine/workspace/` holds Syneidesis selection and the `RuleBasedSalience` factors. It must not import `kaine/modules/`. Salience factors that need module-produced signals — such as Thymos affect state or goal drive levels — receive them by dependency injection at cycle assembly. The cycle constructs the real `StateModulator` and refreshes an `AffectStateProvider` each tick from `thymos.state`.

There are no `ignore_imports` exceptions for this rule. Any `from kaine.modules... import ...` inside `kaine/workspace/` is a boundary violation.

### Evaluation and Nexus

`kaine/evaluation/` must not import `kaine/nexus/` internals. The sidecar observes the bus and runs headless; Nexus is only a presentation seam.

### Neutral homes stay neutral

The boundary-neutral homes must not import the core runtime or `kaine/evaluation/`. That bidirectional rule is what lets core reuse them without dragging in research, and lets research reuse them without depending on the entity.

## Plugin contracts

The import contracts also protect three plugin boundaries, defined in [`pyproject.toml`](../../pyproject.toml):

- `kaine/modules/` must not import `kaine/plugins/`.
- `kaine/plugins/` must not import boot (`kaine/boot.py`), cycle (`kaine/cycle/`), or modules (`kaine/modules/`).
- Core KAINE must not import `kaine_cl1`.

These rules keep plugins optional and stop core code from depending on a plugin interface.

## Running the check

The contracts live in [`pyproject.toml`](../../pyproject.toml) under `[tool.importlinter]`, with `root_packages = ["kaine"]`. You can run them in three ways, all in seconds and independent of the full test suite:

```bash
# Direct: run all contracts.
.venv/bin/lint-imports

# As a focused pytest gate.
.venv/bin/pytest -k import_boundary

# On every commit, once the hook is installed.
.venv/bin/pre-commit install
.venv/bin/pre-commit run lint-imports --all-files
```

A dedicated GitHub Actions job, [`../../.github/workflows/import-boundary.yml`](../../.github/workflows/import-boundary.yml), installs only `import-linter` and runs `lint-imports`. It is a pure static check with no entity boot, no services, and no secrets, so a violation fails CI with a precise message naming the offending module and the violated contract.

The grep test in [`tests/systems/test_sidecar_subsystem.py::test_boundary_no_core_module_imports_evaluation`](../../tests/systems/test_sidecar_subsystem.py) is an extra safeguard: it catches real `kaine.evaluation` imports, but it does not catch aliased or indirect imports. The import contract catches those.

When you add a new top-level `kaine/` package, add it to the `source_modules` list of the sidecar contract. Neither the linter checks nor the boundary tests verify that `source_modules` is complete, so keep it updated manually. The current list already omits several existing packages, including `accel_selftest`, `cfc_numpy`, `embedding_defaults`, `extras`, `install_target`, `secrets_file`, `text_embedding_numpy`, `torch_stack`, and `wheel_data`.
