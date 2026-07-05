# Process: Run Identity, Seeding, and Manifest

Every cycle run has a single identity. At boot the cycle pins the global random
number generators from one integer seed, mints a unique run id, and stamps that
id plus a per-stream sequence number onto every durable record. A manifest
records the seed, code revision, model ids, and a config digest so any dataset
the run produces can be grouped, checked for gaps, and attributed to a
configuration.

This is the foundation the rest of the research-testing work builds on:
completeness gating reads the per-stream sequence, deterministic ablation reuses
the seed primitive, and freeze annotation attaches to the run id.

Related: [research-operation.md](research-operation.md) ·
[testing-framework.md](testing-framework.md) ·
[run-admissibility.md](run-admissibility.md) ·
[evaluation-sidecar.md](evaluation-sidecar.md) ·
[active-inference-benchmark.md](active-inference-benchmark.md) ·
[../research-participation.md](../research-participation.md)

---

## Global seed

`kaine.experiment.set_global_seed(seed)` pins the legacy `random` and numpy
global RNGs and, best-effort, the torch RNG (including CUDA when present), and
returns the seed used. It never fails when torch is absent or CPU-only.
Per-experiment code keeps using `np.random.default_rng(seed)` for local streams;
the global seed pins the legacy globals and torch so nothing on the cycle path is
silently nondeterministic.

## Run context

`kaine.experiment.RunContext` is an immutable record minted once at boot and held
process-globally, mirroring `kaine.security.crypto.get_state_encryptor`. Modules
and sinks read it through `get_run_context()`, which returns `None` when no run
has started (the library / unit-test default). It carries:

- `run_id` — a fresh uuid4 hex, unique per process start.
- `seed` — the integer pinned by `set_global_seed`.
- `started_at` — an ISO-8601 UTC timestamp.
- `git_sha` — a best-effort short git revision (`None` when git is unavailable;
  resolution never raises).
- `model_ids` — the configured model ids from the documented model keys only
  (language organ, A/B baseline, topos encoder, mnemos embedder, audition STT and
  emotion). Never hostnames, paths, or voice names.
- `config_digest` — `sha256` of the resolved config (truncated), so two runs can
  be compared for "same config" without storing the config itself.
- `kaine_version`.
- `perception_feed` — the reproducible perception-feed descriptor: a small dict
  shaped `{"mode": "off"|"seeded"|"playlist"|"camera", ...}`. For `seeded` it
  carries the seed and schedule parameters (enough to regenerate the stream);
  for `playlist` it carries the manifest sha256 plus per-item digests (enough to
  verify it, not the content itself). An empty dict means the feed contributed
  nothing (mode `off`, or the descriptor was unavailable). The caller gathers
  this at the cycle/boot layer (`kaine.boot.gather_perception_feed_descriptor`)
  and passes it in as data, keeping `kaine.experiment` boundary-neutral — the
  same pattern as `model_ids`. It is non-content: no rendered frames, no
  operator paths.

## Run discovery

`kaine.experiment.run_records.discover_run_ids(root)` enumerates the DISTINCT
`run_id` values present in the eval logs under `root`, by scanning every
`*.jsonl` sink file (the same tree `load_run_records` reads, skipping the
`runs/` manifest directory), decrypting and parsing each line, and collecting
every non-empty `run_id` seen across all of them. It returns a `RunDiscovery`
with `run_ids` (the sorted set found) and `unreadable_lines` (a count of lines,
and whole files on `OSError`, that could not be decrypted/parsed). A non-zero
`unreadable_lines` is itself a signal — usually a wrong or absent state
encryption key — so callers fail closed on it rather than mistaking unreadable
logs for "no run data". This is what lets the research bundle builder gate
admissibility without the operator having to know or pass a run id: the run(s)
are found in the very tree the bundle is built from.

## Record stamping

When a run context is set, every record written through `AsyncJsonlSink` carries
the run's `run_id` and a per-sink monotonic `seq` (from 0). One central edit
covers the research event log, every sidecar observer, the raw archive, and the
Spot incident log. Stamping is done on a shallow copy, so the caller's dict is
never mutated. When no run context is set — the unit-test and library default —
records are written unchanged: neither `run_id` nor `seq` is added.

The per-sink `seq` lets completeness gating detect a silent drop within any
single stream, complementing tick-index gaps across the cycle.

## Manifest

When `[experiment].write_manifest` is true (the default), the cycle writes the
run context once at boot to `data/evaluation/runs/<run_id>/manifest.json` with an
atomic write. The `runs` directory is in the metrics-export allowlist
(`METRICS_ONLY_DIRS`): the manifest holds only the run id, seed, git sha, model
ids, config digest, started-at, and version — no entity interior and no
operator-identifying data — so it is export-eligible.

## Deterministic mode

`[experiment].deterministic` (default `false`) is an opt-in mode that makes a
cycle run **bit-for-bit reproducible**: two runs with the same seed and the same
input sequence produce an identical cognitive trajectory. It is the foundation of
the oscillatory ablation — running the cycle with the precision layer on versus
off, same seed, same input, so any behavioral difference is attributable to the
layer alone rather than to two slightly different random universes.

Beyond the global seed (above), deterministic mode closes two residual sources of
run-to-run variation:

- **Logical event clock.** The engine stamps every event it publishes from a
  single seam, `CognitiveCycle._now()`. In normal mode this is the injectable
  `wall_clock` (real UTC by default). In deterministic mode it is a logical clock:
  tick *k*'s events are stamped `BASE_EPOCH + k * target_tick_period`, where
  `BASE_EPOCH` is the fixed constant `1970-01-01T00:00:00Z` and the target tick
  period is the inverse of the processing rate. Logical timestamps are therefore
  identical across runs. This clock is distinct from the engine's monotonic
  `clock`, which still measures real elapsed time for slip/latency.
- **Canonical within-tick event ordering.** Before scoring and selection, each
  tick's gathered events are sorted by a total deterministic key
  `(source, type, entry_id)`. This pins the selection tie-break input so it no
  longer depends on async-gather or stream-declaration incidentals. The ordering
  is applied **unconditionally** — production and deterministic runs share one
  ordering rule, so the ablation's "only the layer differs" claim is airtight.
  Because the selection score sort is stable and the common case is already
  ordered, this is a no-op for normal runs.

**What is guaranteed:** tick by tick, the same selected coalitions (entry ids,
sources, types, salience scores), the same inhibition decisions, the same volition
outputs, and the same logical event timestamps.

**What is NOT guaranteed:** wall-clock latency. `wall_duration_ms` and `slip_ms`
are physical measurements of the host, inherently variable, and excluded from the
reproducibility guarantee. Real time still elapses and these fields are still
recorded; they simply are not part of what two runs are required to match.

Deterministic mode ships off — production runs use real wall-clock time. The seed
that A1 always sets is recorded in the manifest as usual, so a deterministic run
stays reproducible after the fact.

## Configuration

```toml
[experiment]
# A fixed integer makes a run reproducible. Leave blank to generate a fresh seed
# each boot; the manifest always records whatever seed was used.
seed = ""
# Write data/evaluation/runs/<run_id>/manifest.json at boot.
write_manifest = true
# Opt-in deterministic mode: logical event clock + canonical within-tick event
# ordering so a run is bit-for-bit reproducible (same seed + input → same
# trajectory). Off in production; used by the oscillatory-ablation runner. Does
# NOT make wall-clock latency reproducible.
deterministic = false
```

## Shared verdict schema

`kaine.experiment.verdict` provides one outcome vocabulary every experiment
reports through: `Outcome` (WIN / NULL / NEGATIVE for comparative experiments,
PASS / FAIL for safety gates) and a frozen `Verdict` (outcome, detail, metrics)
with a stable `to_dict()`. The active-inference benchmark and the enforcement
red-team each include a `verdict` object using this schema alongside their
existing fields, so downstream tooling has one shape to read.
