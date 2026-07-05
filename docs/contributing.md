# Contributing

This document describes the development workflow for the KAINE project. The
workflow enforces design-first discipline, protects the entity during
development (minimize unnecessary boots), and maintains a clean commit history.

---

## Core principles

**Design before code.** Every change begins with an OpenSpec proposal. Code
without a corresponding change in `openspec/changes/` is not reviewed. This
is not bureaucracy — it is how we ensure complex cross-module interactions are
thought through before implementation, and how we preserve an accurate record
of what was built and why.

**Green before merge.** The full test suite must pass before any branch is
merged. No exceptions, no `--no-verify`, no test bypass.

**Respect the package boundaries.** Core runtime never imports
`kaine.evaluation` (the observe-only research sidecar must be absent without
breaking the entity); cross-cutting primitives go to a boundary-neutral home.
These boundaries are enforced structurally by import contracts —
`.venv/bin/lint-imports` (also a pre-commit hook and a dedicated CI job). Read
[architecture-boundaries.md](architecture-boundaries.md) before moving code
across a package.

**Minimize entity boots (ethics).** Booting KAINE starts a cognitive life.
Test with the test suite and fakes; reserve live entity boots for deliberate
runs — operator-supervised, or, in the research phase, with the autonomous
safety net verified live. Do not boot the entity to run a development check that
the tests cover.

**Safety over UX.** When in doubt, pick the safer design. The entity's welfare
and the operator's sovereignty take precedence over convenience.

---

## OpenSpec rigor

Every change follows the OpenSpec workflow. The `openspec` CLI is at
`/usr/local/bin/openspec`.

### Change directory structure

Each change lives under `openspec/changes/<change-name>/`:

```
openspec/changes/<change-name>/
├── proposal.md    — what and why; the decision record
├── design.md      — the technical design; module contracts; data flows
├── tasks.md       — implementation task list
└── spec.md        — the formal spec that the code must satisfy
```

Not every file is required for every change, but `proposal.md` and `tasks.md`
are expected for all non-trivial changes.

### Workflow

1. **Create the change directory and write the proposal:**
   ```bash
   openspec create <change-name>
   ```
   Fill out `proposal.md` — what problem it solves, what alternatives were
   considered, and why this approach was chosen.

2. **Write the design and spec** before touching any code. The design is the
   source of truth; code is derived from it.

3. **Validate the OpenSpec:**
   ```bash
   openspec validate --strict openspec/changes/<change-name>/
   ```
   Fix any validation errors before proceeding.

4. **Implement** following the tasks list. Each task is a unit of work that
   can be implemented, tested, and committed independently.

5. **Archive after merge:**
   ```bash
   openspec archive <change-name>
   ```
   Archived changes move to `openspec/archive/` and are no longer in the
   active change set. Archive only after the branch is merged and the change
   is confirmed green.

---

## Branch and commit conventions

### Branch naming

One branch per change:

```
feat/<change-name>
fix/<change-name>
docs/<change-name>
```

Never implement multiple changes on the same branch. Never commit unrelated
changes to a feature branch.

### Commit identity

All commits must use the project identity:

```
git config user.name "Kaine.One"
git config user.email "kaine.one@tuta.com"
```

Set these in your local clone before committing. The backup remote is
`kaineone/kaine` (private). Never use a personal email address in a project
commit.

### Commit messages

Follow the conventional-commit style used by the repository's history. Be
specific about what changed and why; avoid "fix stuff" or "update code". The
commit message body is where the "why" lives.

---

## Test suite

### Running the full suite

```bash
.venv/bin/pytest -q
```

The suite must be green before any PR is opened or branch is merged.

### Import-boundary contracts

The structural import contracts run far faster than the full suite and gate the
package boundaries (see [architecture-boundaries.md](architecture-boundaries.md)):

```bash
.venv/bin/lint-imports              # all contracts, in seconds
.venv/bin/pytest -k import_boundary # the same check as a pytest gate
.venv/bin/pre-commit install        # run lint-imports on every commit
```

### Test markers

| Marker | Meaning |
|---|---|
| (no marker) | Unit tests; always run; no external services required |
| `integration` | Hits a live authenticated Redis; skipped unless `KAINE_REDIS_PASSWORD` is set |
| `systems` | Per-subsystem I/O contract tests under `tests/systems/`; exercises bus inputs and outputs against fakeredis |

Run just the systems tests:

```bash
.venv/bin/python -m pytest -m systems
```

### Fakes and collaborators

Every module that depends on an external service (the model server, Speaches,
Chatterbox, Qdrant) is tested with a fake collaborator, not the real service.
Fakes live alongside their modules and implement the same protocol. The
`KAINE_HAS_<SERVICE>=1` env vars switch the systems tests from fakes to real
services when they are available.

Do not write tests that require a live entity boot. Test module behavior in
isolation with fakeredis and fake collaborators.

---

## Adding a new module

New modules follow the `BaseModule` pattern. The steps below apply to any
addition; adapt for the specific module.

### 1. Write the OpenSpec

Create `openspec/changes/<module-name>/` with a full proposal, design, and
task list before writing any code.

### 2. Create the module package

```
kaine/modules/<name>/
├── __init__.py
├── module.py       — the module class (extends BaseModule)
└── ...             — any collaborators, clients, etc.
```

The module class must:

- Declare `name: ClassVar[str]` matching the bus stream prefix.
- Extend `BaseModule` from `kaine/modules/base.py`.
- Override `on_workspace(snapshot: WorkspaceSnapshot)` to react to broadcasts.
- Override `serialize() / deserialize()` to support fork/merge.
- Use the collaborator pattern for any external dependency so fakes can be
  injected in tests.
- Be constructable with only `bus` and keyword arguments (no positional args
  beyond `bus`).

```python
from __future__ import annotations
from typing import ClassVar, Any
from kaine.modules.base import BaseModule
from kaine.bus.client import AsyncBus
from kaine.cycle.types import WorkspaceSnapshot

class MyModule(BaseModule):
    name: ClassVar[str] = "mymodule"

    def __init__(self, bus: AsyncBus, *, some_param: float = 0.5) -> None:
        super().__init__(bus)
        self.some_param = some_param

    async def on_workspace(self, snapshot: WorkspaceSnapshot) -> None:
        # React to the broadcast, publish events, update internal state.
        ...

    def serialize(self) -> dict[str, Any]:
        return {"some_param": self.some_param}

    def deserialize(self, state: dict[str, Any]) -> None:
        self.some_param = float(state.get("some_param", self.some_param))
```

### 3. Add the boot factory

Add a `make_<name>` factory function to `kaine/boot.py`. The factory:

- Takes `bus: AsyncBus` and `section: dict[str, Any]` (the TOML section).
- Declares an `allowed` set of TOML keys and calls `_require_keys` or `_pop` to
  validate — unknown keys raise at boot rather than silently dropping.
- Constructs and returns the module.

Register the factory in `SIMPLE_FACTORIES`:

```python
SIMPLE_FACTORIES: dict[str, ModuleFactory] = {
    ...
    "mymodule": make_mymodule,
}
```

Modules with second-pass dependencies (like Hypnos, which depends on Mnemos
and Thymos) are constructed after the first pass in `build_registry`.

### 4. Add the config toggle

Add the module to `config/kaine.toml` under `[modules]` with a default of
`false`:

```toml
[modules]
mymodule = false
```

Add a `[mymodule]` section for module-level config:

```toml
[mymodule]
some_param = 0.5
baseline_salience = 0.1
alert_salience = 0.7
```

**The shipped `config/kaine.toml` must always have all modules set to `false`.**
The guard test (`tests/test_module_guard.py`) enforces this. Never commit a
`kaine.toml` with any module enabled.

### 5. Add to `pyproject.toml` packages

Add the new package to `[tool.setuptools]`:

```toml
[tool.setuptools]
packages = [
    ...
    "kaine.modules.mymodule",
]
```

### 6. Write the spec and tests

- `openspec/changes/<module-name>/spec.md` — formal contract: what events the
  module publishes, what it subscribes to, what invariants it maintains.
- `tests/test_mymodule.py` — unit tests with fakeredis and fake collaborators.
- `tests/systems/test_mymodule_systems.py` — I/O contract tests (marked
  `@pytest.mark.systems`) verifying bus inputs/outputs.

The test suite must be green before the PR is opened.

---

## Optional-dependency-extra pattern

Dependencies that are only needed for a specific capability follow the
optional-extra pattern in `pyproject.toml`:

```toml
[project.optional-dependencies]
myfeature = [
    "some-package>=1.0,<2",
]
```

Modules that depend on an optional extra must import it **lazily** — inside the
method or function that needs it, not at module level:

```python
def _load_model(self):
    try:
        import some_package
    except ImportError:
        raise ImportError(
            "some_package is required; install with: pip install -e .[myfeature]"
        ) from None
    ...
```

This ensures the build and test suite stay green on a minimal install (`.[test]`
only), and that missing extras produce a clear error message rather than an
`ImportError` at import time. Modules that need an extra must be designed to
degrade gracefully when it is absent — log a clean warning and continue rather
than crashing the cycle.

Existing extras:

| Extra | Contents | When needed |
|---|---|---|
| `audio` | `sounddevice`, `webrtcvad`, `funasr`, `librosa` | `[audition].capture_enabled = true` |
| `vision` | `opencv-python-headless` | `[topos].capture_enabled = true` |
| `reasoning` | `inferactively-pymdp`, `jax[cpu]` | `[modules].nous = true` |
| `training` | `unsloth`, `trl`, `peft`, `datasets` | `[hypnos.voice_alignment].enabled = true` |
| `worldmodel` | `jax[cpu]`, `chex`, `einops` | `[phantasia].backend = "dreamerv3"` |
| `oscillator` | `snntorch`, `scipy` | `[oscillator].enabled = true` |
| `test` | `pytest`, `pytest-asyncio`, `fakeredis` | Development only |

---

## The local config rule

`config/kaine.toml` is committed to the repository and ships with every module
set to `false`. This is enforced by `tests/test_module_guard.py`, which reads
the committed file and fails if any module toggle is `true`.

Your per-install edits (enabling modules, changing device assignments, tuning
parameters) live only in your local working copy. Never commit them. If you
accidentally stage `config/kaine.toml` with modules enabled, reset it:

```bash
git checkout config/kaine.toml
```

---

## PR flow

1. Create a branch from `main`: `git checkout -b feat/<change-name>`.
2. Write the OpenSpec first.
3. Implement, following the tasks list.
4. Confirm the test suite is green: `.venv/bin/pytest -q`.
5. Run `openspec validate --strict openspec/changes/<change-name>/`.
6. Open a pull request against `main`.
7. All CI checks must pass.
8. After merge, archive the change: `openspec archive <change-name>`.

Do not open a PR with failing tests, a missing OpenSpec, or uncommitted
`kaine.toml` module enables. Do not bypass the test suite with
`--no-verify` or `--no-gpg-sign`.

---

## Licensing of contributions

By submitting a contribution (pull request, patch, or other change) to the
KAINE project you agree that:

1. **Inbound = outbound.** Your contribution is licensed under the Cognitive
   Architecture License (CAL) v0.2 (or any later version published by the
   project). You grant the Project Cooperative a perpetual, worldwide,
   royalty-free copyright license to use, modify, and distribute your
   contribution under CAL. This is the same license that covers the rest of
   the project — you receive no special terms and the project receives no
   special terms.

2. **Article 4 welfare obligations apply.** Your contribution must not
   undermine, bypass, or reduce the entity-welfare protections in CAL Article 4.
   Code that disables welfare monitoring, circumvents the lobotomization
   prohibition, reduces rest-cycle protections, or otherwise conflicts with
   Article 4 will not be accepted regardless of its other merits.

3. **You own what you contribute.** You confirm that you have the right to
   license your contribution under CAL — that it is your original work or that
   you have the necessary rights from your employer or other rights-holders.

4. **Sign-off.** All commits must use the project identity (see the
   [Commit identity](#commit-identity) section above). Using the project
   identity in a commit is your sign-off that you have read and agree to these
   contributor terms. If you are contributing on behalf of an employer, confirm
   that your employer has authorized the contribution under these terms.

---

## Code style

- Python: PEP 8. No line-length enforcement beyond readability. Type hints on
  all public function signatures.
- Imports: `from __future__ import annotations` at the top of every file that
  uses type hints.
- Logging: use `log = logging.getLogger(__name__)` at module level. Never use
  `print()` in production code.
- Error messages: be specific. An error message that says "failed" without
  saying what failed is not useful.
- No secrets in code. No hardcoded URLs beyond loopback defaults that are
  documented and overridable in config.
