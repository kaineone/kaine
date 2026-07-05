# Design: experiment run identity

## Package placement and the sidecar boundary

The foundation lives in a new `kaine/experiment/` package. Like
`kaine/persistence/` and `kaine/security/`, it carries no dependency on
`kaine.evaluation`, so **both** the core cycle and the evaluation sidecar may
import it without violating the boundary test (only the cycle/nexus entrypoints
may import `kaine.evaluation`). It depends only on stdlib + numpy + optional torch.

## set_global_seed

```
def set_global_seed(seed: int) -> int:
    random.seed(seed)
    numpy.random.seed(seed)            # legacy global; default_rng(seed) used per-experiment
    try: import torch; torch.manual_seed(seed); (cuda manual_seed_all if available)
    except Exception: pass
    return seed
```
Best-effort on torch (CPU-only / absent installs must not fail). Returns the seed
so the caller records exactly what was set. Per-experiment code keeps using
`np.random.default_rng(seed)` for local streams; this only pins the legacy globals
+ torch so nothing in the cycle path is silently nondeterministic. (Full cycle
determinism — event ordering, injectable clock — is the separate
`deterministic-cycle-mode` change; this change provides the seed primitive it
will use.)

## RunContext (process-global)

```
@dataclass(frozen=True)
class RunContext:
    run_id: str            # uuid4 hex, minted at boot
    seed: int
    started_at: str        # ISO-8601 UTC (passed in; clock not called at import)
    git_sha: str | None
    model_ids: dict[str, str]
    config_digest: str     # sha256 of the resolved config mapping
    kaine_version: str
```
`set_run_context(ctx)` / `get_run_context() -> RunContext | None` hold it in a
module global, exactly like `kaine/security/crypto.py::get_state_encryptor()`.
`get_run_context()` returns `None` when unset (the unit-test / library default),
which is what keeps record-stamping inert outside a real run.

`git_sha`: best-effort `git rev-parse --short HEAD` via subprocess with a short
timeout; `None` on any failure (no git, detached, timeout). Never raises.

`config_digest`: `sha256(json.dumps(resolved_config, sort_keys=True))[:16]` — lets
two runs be compared for "same config" without storing the (operator-specific)
config itself.

## Record stamping in AsyncJsonlSink

`AsyncJsonlSink.write()` (and `write_sync`) merge run identity into each record
*before* encode, only when a context exists and the keys aren't already present:

```
ctx = get_run_context()
if ctx is not None:
    entry.setdefault("run_id", ctx.run_id)
    entry["seq"] = self._next_seq()      # per-sink monotonic, from 0
```
- Central: one edit covers research events, every sidecar observer, the raw
  archive, and the Spot incident log (all write through `AsyncJsonlSink`).
- `seq` is per-sink monotonic so completeness-gating (next change) can detect a
  silent drop within any single stream, complementing `tick_index` gaps across
  the cycle.
- Inert without a context → the existing sink tests and the 1900+ unit suite are
  unchanged (no `run_id`/`seq` keys appear).
- `import` of `kaine.experiment.run_context` into `kaine/persistence/` is
  boundary-clean (experiment ⟂ evaluation).

## Manifest

Written once at boot to `data/evaluation/runs/<run_id>/manifest.json` (atomic
write). Contains the full `RunContext` as JSON. The dir name `runs` is added to
`METRICS_ONLY_DIRS` so it rides the existing metrics export. Rationale for
export-safety: the manifest holds run_id (random), seed (int), git_sha (public
once the repo is published), model_ids (the abliterated tag etc. — already in the
shipped config), config_digest (a hash, not the config), and kaine_version — no
entity interior, no operator hostnames/paths/voice. The model_ids dict is built
from the config's documented model keys only (lingua/eval/topos/mnemos/audition),
never from anything operator-identifying.

## Verdict schema

`kaine/experiment/verdict.py`:
```
class Outcome(str, Enum): WIN="WIN"; NULL="NULL"; NEGATIVE="NEGATIVE"; PASS="PASS"; FAIL="FAIL"
@dataclass(frozen=True)
class Verdict: outcome: Outcome; detail: str = ""; metrics: dict = {}
    def to_dict(self) -> dict: ...
```
The AIF benchmark already emits WIN/NULL/NEGATIVE and the red-team PASS/FAIL —
adoption is additive: each report includes a `verdict` object using this schema
alongside its existing fields, so downstream tooling has one shape to read. No
existing field is removed.

## Config

```
[experiment]
# Fixed seed for a reproducible run. Leave blank to generate (and record) a fresh
# seed each boot — the manifest always captures whatever seed was used.
seed = ""
write_manifest = true
```

## Test strategy

- `set_global_seed` pins numpy/random reproducibly; torch path is best-effort and
  does not fail when torch is CPU-only/absent.
- `RunContext` round-trips to/from the manifest JSON; `git_sha` falls back to
  `None` without raising when git is unavailable (mock subprocess failure).
- `AsyncJsonlSink` stamps `run_id` + monotonic `seq` when a context is set, and
  writes **no** such keys when none is set (inertness guard).
- `config_digest` is stable across identical configs and differs on change.
- The manifest dir name is in `METRICS_ONLY_DIRS` and contains no deny-pattern
  substring.
- Boot wiring: the entrypoint mints + sets the context and writes the manifest
  (test at the `_load`/boot seam without launching the entity).
- Verdict serialization is stable; AIF + red-team reports include a `verdict`.
