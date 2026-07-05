# Deterministic cycle mode

## Why

The oscillatory ablation is the cleanest experimental contribution: run the cycle
with the precision layer on vs off, same seed, same input, and attribute any
behavioral difference to precision modulation alone. That argument only holds if a
run is **bit-for-bit reproducible** — otherwise the ablation compares two slightly
different random universes, not layer-on vs layer-off.

Today it isn't reproducible. `experiment-run-identity` (A1) pinned the global seed,
and the selection/volition path has no RNG — but event **timestamps** are taken
with `datetime.now(timezone.utc)` at three sites in the engine
(`engine.py:264, 317, 533`), bypassing the already-injectable `_clock`, so every
run's logs differ. And the within-tick ordering of events gathered across modules
is an *implicit* contract (stream-declaration order), never asserted, so a change
to dispatch could silently reorder selection tie-breaks.

This change adds an opt-in **deterministic mode**: a logical clock for event
timestamps, a canonical within-tick event ordering, and a test proving two runs
with the same seed + input produce identical workspace trajectories and decisions.

## What Changes

- **Injectable event timestamps.** The engine gets a `wall_clock: () -> datetime`
  seam (default `lambda: datetime.now(timezone.utc)`); the three `datetime.now`
  sites call it. In deterministic mode the wall clock is a **logical clock**:
  `base_epoch + tick_index * tick_period`, so timestamps are identical across runs.
- **Canonical within-tick event ordering.** Before selection, the per-tick event
  list is ordered by an explicit, total deterministic key (source, type, entry_id)
  so selection tie-breaks no longer depend on async gather/stream-declaration
  incidentals. (Selection's score sort is already stable; this pins the tie-break
  input.)
- **`[experiment].deterministic` flag** (default false). When true at boot: the
  run uses the logical clock and the canonical ordering, and requires a fixed seed
  (A1 always sets one — deterministic mode records it as usual). Production runs
  leave it false and keep real wall-clock time.
- **Determinism test.** A scripted-input harness runs the cycle twice in
  deterministic mode with the same seed and asserts identical workspace
  trajectories (selected entries + salience scores + inhibited flags), identical
  volition decisions, and identical logical timestamps across N ticks. Wall-clock
  latency fields (`wall_duration_ms`, `slip_ms`) are explicitly **excluded** from
  the identity comparison — they are inherently nondeterministic and are not part
  of the reproducibility guarantee.

## Impact

- Affected: `kaine/cycle/engine.py` (wall-clock seam + canonical ordering),
  `kaine/cycle/__main__.py` (wire the flag), `config/kaine.toml` (`deterministic`
  key under `[experiment]`).
- Ships off (`deterministic = false`) → production behavior unchanged; the engine's
  default wall clock is the real clock and ordering change is a stable no-op for
  the existing already-deterministic case.
- Builds on A1 (`experiment-run-identity`): uses the seed A1 sets and the run
  manifest records it. Enables the Phase-D oscillatory-ablation runner.
- The reproducibility guarantee covers the cognitive trajectory + decisions +
  logical timestamps, NOT wall-clock latency (documented as out of scope).
