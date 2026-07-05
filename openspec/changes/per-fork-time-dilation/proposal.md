# Per-fork subjective-time profile (Phase 4 of biological timing)

## Why

The biological-timing core (merged #89) gave the entity a single subjective
`EntityClock` with a global `time_scale`. The operator's temporary-being research
direction wants a **forked being to run at its own subjective speed** — e.g. fork
a copy, let it think faster (or slower) than wall-clock on a directive, then
remerge and assimilate what it learned.

The forking machinery this needs **already exists** and must not be duplicated:
`kaine/lifecycle/manager.py` `ForkManager` already does fork → run → `merge()`
with per-module knowledge assimilation (`lifecycle/strategies.py`), plus
snapshot/restore/preserve/revive. The **only** missing piece for *dilated*
temporary beings is letting a fork carry, and apply at spawn, its own
`time_scale` (and optionally per-rate overrides). That is a small, additive
field on the existing fork — not a new system.

## What changes

1. **A fork may carry a subjective-time profile** in its existing
   `ForkSnapshot.metadata` (a `timing` sub-dict: `time_scale`, optional
   `processing_rate_hz` / `experiential_rate_hz` / `vision_sample_hz` overrides).
   `ForkManager.fork(...)` already accepts `metadata`, so no new storage.
2. **The runtime applies the profile when a fork is restored to run** — a small
   `apply_fork_timing_profile(snapshot, entity_clock, cycle)` seam reads the
   profile and applies it via the **existing** `EntityClock.scale` setter and the
   **existing** `cycle.set_rates` path. A fork with no profile runs at the
   prevailing scale (behavior-preserving).
3. **The `POST /forks` API gains an optional `time_scale`** (+ optional rate
   overrides) on `ForkRequestBody`, threaded into `fork(metadata=...)`.

Explicitly **out of scope** (and unchanged): the fork/merge/assimilation system
itself (already built), and running a fork *concurrently* alongside the live
parent (that is the separate `distributed-substrate` work). This change only adds
the per-fork timing field and its apply-at-spawn seam.

## Impact

- **Capability:** extends `entity-time` (the per-fork profile) and touches
  `entity-preservation` (fork metadata) and `nexus-dashboard` (the `/forks` API).
- **Code:** `kaine/lifecycle/` (profile helper on the snapshot/metadata), a small
  apply seam wired where the cycle restores a fork, `kaine/nexus/diagnostics.py`
  (`ForkRequestBody` + `create_fork`). Reuses `EntityClock.scale` and
  `cycle.set_rates` — no new mechanisms.
- **Behavior-preserving:** forks without a timing profile behave exactly as today.
- **No entity boot.**
