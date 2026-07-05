## Why

Paper §4.3 frames forking and merging as "three distinct operations
that exist on a spectrum from tool to person": full fork (new
person), analytical lens (short-lived task fork, ethically a tool),
and merge (a NEW entity rather than a restoration). Build prompt
§7.2 specifies the components: full state serialization, fork with
optional module shedding and different cycle rate, merge with
NARS revision + memory union with source tags + emotional history
as recalled memories + Eidolon reconciliation + LoRA TIES/DARE.

Phase 7.2 ships the orchestration: a `ForkSnapshot` shape, a
`ForkManager` that captures and persists snapshots, per-module merge
strategies the registry can compose, and a clear documented stub for
the LoRA-adapter TIES/DARE step.

## What Changes

- Introduce `kaine.lifecycle` (top-level package, not under
  modules — it operates ACROSS modules):
  - `snapshot.py` — `ForkSnapshot` dataclass (id, parent_id, label,
    timestamp, modules: dict[str, dict], adapters: list[Path],
    metadata: dict). Atomic save/load to JSON files under
    `state/forks/<id>/snapshot.json`.
  - `manager.py` — `ForkManager.snapshot(registry, *, label)`
    captures every registered module's `serialize()` output and
    writes a snapshot. `ForkManager.restore(snapshot_id, registry)`
    loads + calls each module's `deserialize()`.
    `ForkManager.fork(parent_id, *, label, shed=[])` produces a child
    snapshot with optional module-shedding.
    `ForkManager.merge(snapshot_a_id, snapshot_b_id, *, label,
    strategies)` runs per-module merge strategies and writes the
    merged snapshot. Adapter merge is delegated to an `AdapterMerger`
    protocol (real TIES/DARE is operator-opt-in via a follow-up).
  - `strategies.py` — `MergeStrategy` protocol +
    default implementations: `UnionMergeStrategy` (general dict
    union), `MnemosMergeStrategy` (union short_term + tag sources),
    `NousMergeStrategy` (combine beliefs via additive truth-value
    revision sketch — the real NARS revision happens inside ONA at
    next inference cycle), `EidolonMergeStrategy` (sum drift_count,
    union values and norms, combine identity_history with source
    tags), `ThymosMergeStrategy` (average baselines, max drives,
    union goals).
- `[lifecycle]` block in `config/kaine.toml` for snapshot path, max
  retained snapshots, adapter-merge backend selector.
- Tests cover snapshot roundtrip, fork-with-shed, per-module merge
  strategies, end-to-end merge across all of Soma/Chronos/Topos/
  Nous/Mnemos/Thymos/Eidolon/Lingua/Praxis/AudioIn/AudioOut.

## Capabilities

### New Capabilities

- `fork-merge`: cross-module state lifecycle. Owns the ForkSnapshot
  shape, the ForkManager API, the per-module merge strategies, and
  the AdapterMerger protocol.

### Modified Capabilities

None — fork/merge orchestrates existing module `serialize/deserialize`
contracts without modifying any module spec.

## Impact

- **Depends on:** every module's `BaseModule.serialize/deserialize`
  (already shipped in Phase 1.4 and respected by every module).
- **Repo:** adds `kaine/lifecycle/*.py`, `tests/test_fork_merge_*`,
  updates `pyproject.toml` packages, `config/kaine.toml`. Gitignored
  `state/forks/`.
- **No new external deps.** Adapter TIES/DARE is documented as a
  follow-up gated by operator opt-in.
- **No runtime impact.** No module is changed; only the lifecycle
  manager is added.
