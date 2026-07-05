# Architecture Boundaries

KAINE's package layout encodes load-bearing architectural boundaries. These
are not stylistic preferences — they protect properties the system depends on,
above all that the **core cognitive runtime runs with the research
instrumentation entirely absent**. The boundaries are enforced structurally by
import contracts (`import-linter`), not only by convention or a string search.

This document is the first thing a contributor (human or agent) reads before
moving code that crosses a package: it names the layers, the two allowed seams,
the boundary-neutral homes for cross-cutting primitives, and how to run the
check locally.

---

## The sidecar boundary (load-bearing)

`kaine/evaluation/` is the **observe-only research subsystem** — the eight
sidecar observers, A/B divergence, the individuation-boundary instrument, the
red-team harness, the benchmarks. It reads the bus and module state; it never
injects into the cognitive loop.

The boundary is: **core never imports `kaine.evaluation`.** The entity must be
able to boot and run a full cognitive life with the entire `evaluation` package
deleted from disk — research instrumentation is strictly additive and optional.
If core code reached into `kaine.evaluation`, removing or disabling the sidecar
would break the entity, and the "instrumentation is observe-only" guarantee
would be a fiction.

### The two allowed seams

Exactly two modules — the **composition roots** — may wire the sidecar in:

| Seam | Role |
|------|------|
| `kaine/cycle/__main__.py` | Boots the cognitive cycle; constructs the sidecar registry if evaluation is enabled. |
| `kaine/nexus/__main__.py` | Boots the operator UI process; surfaces sidecar output. |

These are entrypoints, not library code. Nothing imports *them*. They are the
only place the two halves are composed, so the dependency points one way
(entrypoint → both halves) and never core → evaluation.

### The rule for cross-cutting logic

The research work keeps producing core components that need logic which
historically lived in evaluation — a JSONL sink, a privacy filter, a
sustained-distress detector, a welfare-count helper. The rule is:

> **Core never imports `kaine.evaluation`. Cross-cutting primitives that both
> sides need go to a boundary-neutral home** — a package that depends on
> *neither* the core runtime *nor* evaluation.

When you find yourself wanting to `from kaine.evaluation import X` in a core
module, that is the signal to extract `X` to a neutral home instead.

### Boundary-neutral shared homes

These hold primitives shared by both sides. They import neither the core
runtime (`cycle`, `modules`, `nexus`, `workspace`) nor `evaluation`:

| Home | Contents |
|------|----------|
| `kaine/persistence` | `AsyncJsonlSink` and persistence primitives. |
| `kaine/experiment` | Experiment helpers (e.g. `welfare_counts`). |
| `kaine/privacy_filter.py` | `PrivacyFilter` — content redaction. |
| `kaine/text_embedding.py` | The text embedder. |
| `kaine/lifecycle/welfare_signal.py` | The sustained-distress detector. |

Keeping these neutral is what lets a core component reuse them without dragging
in evaluation, and lets evaluation reuse them without depending on core.

---

## Declared layering

Beyond the sidecar boundary, the contracts declare the project's real layering
so it is enforced and documented rather than implicit.

### Modules → `kaine.cycle.types` only (contract-only exception)

The domain organs in `kaine/modules/` are leaf components driven by the cycle;
they must not import the cycle **runtime** (the engine/loop, registry,
preflight, boot, `__main__`, the Spot supervisor, the preservation/research
monitors). The one allowed dependency is the pure data/contract module
**`kaine.cycle.types`** (`WorkspaceSnapshot`) — the shape of the broadcast a
module reacts to. That import is permitted directly and transitively (e.g.
through neutral collaborators like `kaine.faithful` and
`kaine.workspace.volition`), and is the single declared exception to
"modules ⊥ cycle."

### Workspace ⊥ cognitive modules (dependency injection only)

The global-workspace layer (`kaine/workspace/` — Syneidesis selection and the
`RuleBasedSalience` factors) must not import the cognitive organs in
`kaine/modules/`. The salience factors that need module-produced signals — the
Thymos factor's affect state and the goal factor's drive levels — receive them
by **dependency injection at cycle assembly**: the cycle constructs the real
`StateModulator` and feeds both factors from an `AffectStateProvider` it refreshes
each tick from `thymos.state`. Because that seam exists, the workspace never
legitimately needs to import a module, so the contract has **no `ignore_imports`
exceptions**: any `from kaine.modules... import ...` inside `kaine/workspace/`
(e.g. importing `StateModulator` directly) is a boundary violation and breaks the
build.

### Evaluation ⊥ Nexus internals

The sidecar observes the bus and must run headless; it does not reach into the
Nexus operator UI internals. Nexus stays a pure presentation seam.

### Neutral homes ⊥ both sides

The boundary-neutral homes listed above are forbidden from importing either the
core runtime or evaluation, so they stay reusable from both sides.

---

## Running the check

The contracts live in `pyproject.toml` under `[tool.importlinter]`
(`root_packages = ["kaine"]`). They are enforced in three places, all fast and
independent of the ~8-minute full test suite:

```bash
# Direct: run all contracts (seconds).
.venv/bin/lint-imports

# As a focused pytest gate.
.venv/bin/pytest -k import_boundary

# On every commit, once the hook is installed.
.venv/bin/pre-commit install
.venv/bin/pre-commit run lint-imports --all-files
```

A dedicated GitHub Actions job (`.github/workflows/import-boundary.yml`)
installs only `import-linter` and runs `lint-imports` — a pure static check
with no entity boot, no services, and no secrets, so a violation fails CI in
seconds with a precise message naming the offending module and the violated
contract.

The grep boundary test in
`tests/systems/test_sidecar_subsystem.py::test_boundary_no_core_module_imports_evaluation`
is kept as belt-and-suspenders so the guarantee survives even if the linter
config is ever removed; the import contract is the primary enforcement (it also
catches `import kaine.evaluation as ...` and indirect imports, which the grep
does not).

> **Adding a new top-level `kaine/` package** means adding it to the
> `source_modules` list of the sidecar contract, and **adding a new
> `kaine/cycle/` runtime submodule** means adding it to the modules-⊥-cycle
> `forbidden_modules` list. The dedicated CI job and the grep test catch a
> stale list.
