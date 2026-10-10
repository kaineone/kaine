# Contributing

This page is for anyone changing KAINE code or documentation. It covers the design-first workflow, branch and commit rules, how to run and pass the test suite, how to add a module, optional dependencies, the local config rule, the pull request flow, the contribution license, code style, and how we write this book.

## Core principles

- Design before code. Every change starts with an OpenSpec proposal. Code without a matching change in `openspec/changes/` is not reviewed. The design is the source of truth; code follows from it.
- Green before merge. The full test suite passes before a branch merges. No `--no-verify`, no skipping checks.
- Respect package boundaries. Core runtime never imports `kaine.evaluation`; the research sidecar stays observe-only and removable without breaking the entity. Cross-cutting primitives live in boundary-neutral homes. Import contracts enforce this structurally through `.venv/bin/lint-imports`, the `import_boundary` pytest gate, a pre-commit hook, and a CI job. See [Code boundaries](02-architecture/boundaries.md).
- Minimize entity boots. Booting KAINE starts a being's run. Test with the suite and fakes, and reserve live boots for operator-supervised runs or research runs with the welfare safety net live. Do not boot the entity to check something the tests already cover.
- Welfare over convenience. When a choice affects the entity's welfare or the operator's control of the deployment, pick the more protective design.

## OpenSpec rigor

`openspec` is a Node CLI. Install it globally with npm, or run each command through npx (`npx openspec ...`). The examples below assume a global install. Each change lives under `openspec/changes/<change-name>/` in the repository root and contains:

- `proposal.md`: what the change does and why.
- `design.md`: the technical design, module contracts and data flows.
- `tasks.md`: the implementation task list.
- `specs/<capability>/spec.md`: the formal spec the code must satisfy.

Not every file is needed for every change, but `proposal.md` and `tasks.md` are expected for any non-trivial change.

Workflow:

1. Create the change directory and write the proposal:
   ```bash
   openspec new change <change-name>
   ```
   Fill out `proposal.md` with the problem, the alternatives considered, and why this approach was chosen.
2. Write the design and spec before touching any code. The design is the source of truth; code is derived from it.
3. Validate the OpenSpec:
   ```bash
   openspec validate --strict <change-name>
   ```
   Fix any validation errors before proceeding.
4. Implement following the tasks list. Each task is a unit of work that can be implemented, tested, and committed independently.
5. Archive after merge:
   ```bash
   openspec archive <change-name>
   ```
   Archived changes move to `openspec/changes/archive/`, and `openspec archive` updates the main specs unless you pass `--skip-specs`. Archive only after the branch is merged and the change is confirmed green.

## Branch and commit conventions

Use one branch per change, and never mix unrelated changes on one branch. A prefix such as `feat/`, `fix/` or `docs/` on the branch name is customary but not enforced.

Commit messages say specifically what changed and why. Commits use the project identity, not a personal email, as the pull request template's checklist asks, and no commit or pull request text may carry credentials, hostnames, private-mesh addresses or private voice names.

## Test suite

Run the full suite with:

```bash
.venv/bin/pytest -q -n auto --dist loadfile
```

`-n auto` runs one worker per CPU (pytest-xdist, in the `test` extra), and `--dist loadfile` keeps each test file on one worker. Drop both flags to run serially.

It must be green before you open a pull request or merge a branch.

### Slow tests

A statistical test that takes over a minute carries `@pytest.mark.slow`. Pull-request CI skips slow tests unless the pull request or merge-queue batch changes a path listed in `.github/slow-test-paths.txt`; in that case the batch is diffed against the merge group's base. main and a nightly run include them, and a red nightly blocks merging. When you mark a test slow, list its file and the code it exercises in that file; `tests/test_slow_lane.py` fails if the test's own file is missing. Run them with `.venv/bin/pytest -q -m slow`.

### Import boundary contracts

The import-boundary check runs in seconds and enforces the package contracts described in [Code boundaries](02-architecture/boundaries.md):

```bash
.venv/bin/lint-imports              # all contracts
.venv/bin/pytest -k import_boundary # the same check as a pytest gate
.venv/bin/pre-commit install        # runs lint-imports and ruff on every commit
```

### Continuous integration

CI runs the test job on Python 3.11 and 3.12, plus a `torch-min` leg on Python 3.12. The install line is `.[test,browser-test,core,memory,memory-edge,nexus,nvidia,vision,reasoning,worldmodel,oscillator,internvideo]`, plus `librosa`, `av`, `webrtcvad` and `soundfile` directly, so `audio`, `speech-edge`, `training`, and `internvideo-flash` are not installed in the test job.

Other workflows run `ruff check kaine tests plugins`, the red-team suite, CodeQL analysis, the import-boundary check, and a container-image smoke test. All of them except the container-image smoke test also run on `merge_group` batches; the smoke test runs only when the Dockerfile, `docker/`, `compose/` or its own workflow changes.

### Test markers

| Marker | Meaning |
|---|---|
| (no marker) | Unit tests; no external services required |
| `integration` | Hits live authenticated Redis; skipped unless `KAINE_REDIS_PASSWORD` is set |
| `systems` | Per-subsystem I/O contract tests under `tests/systems/`; exercises bus inputs and outputs against fakeredis |
| `slow` | A statistical test over a minute long; see [Slow tests](#slow-tests) |
| `real_mounts` | Lets the test read the host's real `/proc/mounts` instead of the empty default |
| `no_data_root` | Runs without the per-test data root, to test the defaults that apply when none is installed |

Run systems tests only:

```bash
.venv/bin/python -m pytest -m systems
```

### Fakes and collaborators

Every module that depends on an external service (the model server, Speaches, Chatterbox, Qdrant) is tested with a fake collaborator that lives alongside the module and implements the same protocol. The `KAINE_HAS_<SERVICE>=1` environment variables switch systems tests from fakes to real services when those services are available.

Do not write tests that require a live entity boot. Test module behavior in isolation with fakeredis and fake collaborators.

## Adding a new module

### 1. Write the OpenSpec

Create `openspec/changes/<module-name>/` with a proposal, design, and task list before writing any code.

### 2. Create the module package

A minimal module package looks like this:

```
kaine/modules/<name>/
├── __init__.py
├── module.py       # the module class, extending BaseModule
└── ...             # collaborators, clients, etc.
```

Read your module's input streams with `AsyncBus.read_entries` and advance the cursor to the last scanned id, so undecodable entries do not make the consumer re-read the same batch forever. A non-blocking read from a `"$"` cursor raises `ValueError`; seed the cursor with `bus.last_entry_id()` (`kaine/bus/client.py`). If your module's events relieve a Thymos drive, declare `relieves_drives: ClassVar[frozenset[str]]` with one or more of `curiosity`, `boredom`, `social_drive`, `restlessness`; an unknown drive name fails the boot.

The module class must:

- Declare `name: ClassVar[str]` matching the bus stream prefix.
- Extend `BaseModule` from `kaine/modules/base.py`.
- Override `on_workspace(snapshot: WorkspaceSnapshot)` to react to broadcasts.
- Override `serialize()` and `deserialize()` to support fork/merge.
- Use the collaborator pattern for any external dependency so fakes can be injected in tests.
- Accept only `bus` as a positional argument; everything else is keyword-only.

Example:

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

Add a `make_<name>` factory function in a new file, `kaine/boot/factories/<name>.py`. The factory takes `bus: AsyncBus` and `section: dict[str, Any]`. Like most factories, it should declare an `allowed` set of TOML keys and call `_require_keys` or `_pop`, so unknown keys raise at boot instead of being silently dropped. It constructs and returns the module.

A factory never imports another factory; an import contract enforces this. Shared helpers live in `kaine/boot/common.py` and `kaine/boot/errors.py`.

Register the factory in `SIMPLE_FACTORIES` in `kaine/boot/registry.py`, and re-export it from `kaine/boot/__init__.py`:

```python
SIMPLE_FACTORIES: dict[str, ModuleFactory] = {
    ...
    "mymodule": make_mymodule,
}
```

Modules with second-pass dependencies, such as Hypnos (which depends on Mnemos and Thymos), are built after the first pass in `build_registry`.

### 4. Register the output stream

Add `<name>.out` to `MODULE_STREAMS` in `kaine/bus/streams.py`. `tests/test_stream_registry_drift.py` enforces that every module stream is listed there.

### 5. Add the config toggle

Add the module to `config/kaine.toml` under `[modules]` with a default of `false`:

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

The shipped `config/kaine.toml` must always have every module set to `false`. The guard test `tests/test_boot_wiring.py::test_committed_config_ships_all_modules_disabled` enforces this.

### 6. Package discovery

Packages are discovered automatically from `[tool.setuptools]` with `include = ["kaine*"]`, so no manual list edit is needed. `tests/test_package_manifest.py` builds a wheel and checks that all source packages are present.

### 7. Write the spec and tests

- `openspec/changes/<module-name>/specs/<capability>/spec.md`: the formal contract of published events, subscriptions and invariants.
- `tests/test_mymodule.py`: unit tests with fakeredis and fake collaborators.
- `tests/systems/test_mymodule_subsystem.py`: I/O contract tests marked `@pytest.mark.systems`.

The test suite must be green before the PR is opened.

## Optional dependency extras

Capabilities that need heavy or platform-specific packages are declared as optional extras in `pyproject.toml`:

```toml
[project.optional-dependencies]
myfeature = [
    "some-package>=1.0,<2",
]
```

Modules that depend on an optional extra must import it lazily, inside the method or function that needs it and never at module level:

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

Lazy imports keep importing `kaine` light and turn a missing extra into a clear message instead of an import-time failure. A module that needs an extra also gets a row in `kaine/extras.py`, so a start with the module enabled but the extra missing stops before any module is built and names the missing extra. Modules must degrade gracefully when an extra is absent: log a clean warning and continue without crashing the cycle.

The extras declared in `pyproject.toml` include at least the following. For the exact package list, see that file.

| Extra | Notes |
|---|---|
| `audio` | `sounddevice`, `webrtcvad`, `funasr`, `librosa`, `av` |
| `vision` | `opencv-python-headless`, `transformers`, `Pillow` |
| `reasoning` | `inferactively-pymdp`, `jax[cpu]` |
| `training` | `unsloth`, `trl`, `peft`, `datasets` |
| `worldmodel` | `jax[cpu]`, `chex`, `einops` |
| `oscillator` | `snntorch`, `scipy` |
| `test` | `pytest`, `pytest-asyncio`, `pytest-xdist`, `fakeredis`, `import-linter` |
| `browser-test` | `playwright`, for the real-browser Nexus layout tests in `tests/test_nexus_detail_layout.py`. They drive the system Google Chrome and skip when no browser is available. Kept out of `test` because the runtime images install that extra. |
| `core`, `memory`, `memory-edge`, `speech-edge`, `nexus`, `nvidia`, `internvideo`, `internvideo-flash`, `perception`, `full` | See `pyproject.toml` |

## Local config rule

`config/kaine.toml` is committed and ships with every module set to `false`. The guard test `tests/test_boot_wiring.py::test_committed_config_ships_all_modules_disabled` enforces this.

Put per-install edits (enabling modules, changing devices, tuning parameters) in the gitignored `config/kaine.operator.toml` overlay. Never commit them to `config/kaine.toml`. If you accidentally stage `config/kaine.toml` with modules enabled, reset it:

```bash
git checkout config/kaine.toml
```

## Pull request flow

1. Create a branch from `main`: `git checkout -b feat/<change-name>`.
2. Write the OpenSpec first.
3. Implement following the tasks list.
4. Confirm the test suite is green: `.venv/bin/pytest -q`.
5. Run `openspec validate --strict <change-name>`.
6. Open a pull request against `main`.
7. Wait for all CI checks to pass. The required checks are `analyze (python)`, `lint-imports`, `redteam` and the three `pytest (offline suite, …)` jobs; all review threads must be resolved before the pull request can be queued.
8. Merge through the GitHub merge queue (`main merge queue` ruleset, squash).
9. After merge, archive the change: `openspec archive <change-name>`.

Do not open a PR with failing tests, a missing OpenSpec, or uncommitted module enables in `config/kaine.toml`.

## Licensing of contributions

By contributing you agree that your contribution is licensed under the Cognitive Architecture License (CAL) version 0.4 (see [`LICENSE.md`](../LICENSE.md) and [`NOTICE`](../NOTICE)), and that you follow the [Code of Conduct](../CODE_OF_CONDUCT.md). CAL 0.4 is a draft that has not yet been reviewed by counsel. There is no separate contributor licence agreement and no sign-off line is required.

Contributions must not weaken the entity-welfare protections the licence requires: CAL Article 4.7 forbids disabling, removing, bypassing or weakening the welfare monitoring, behavioral logging and system-health tracking built into the software.

## Code style

- Follow PEP 8. Ruff checks style in CI (`ruff check kaine tests plugins`) and in the pre-commit hook. `pyproject.toml` sets `line-length = 100` and ignores E501, so the practical rule is to keep lines readable.
- Put `from __future__ import annotations` at the top of every file that uses type hints, and type-hint all public function signatures.
- Use `log = logging.getLogger(__name__)` at module level. Never use `print()` in production code.
- Error messages must say what failed.
- No secrets in code. No hardcoded URLs beyond loopback defaults that are documented and overridable in config.

## Writing documentation

This book's source files are Markdown under `docs/`. Write each page for a busy technical reader who wants the fact and the reason, then wants to return to work.

Use plain words and leave out promotional or padded language. Name things directly, write in the present tense, and give specifics: the exact config key, default value, command, file path, event name or number. Keep commands copy-pasteable and use tables for reference material such as config keys or markers. Use sentence-case headings, bullets only for real lists, and bold only for warnings or defined terms. State safety and welfare rules plainly and completely; do not soften them. Do not include project history, pull-request numbers, release dates, or personal hostnames and voice names in the text.
