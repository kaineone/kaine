# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

## Why

The oscillatory-binding layer (`CoherenceScorer`, PLV-based coalition salience
multiplier) is wired into Syneidesis selection, and the determinism keystone
(`CognitiveCycle(deterministic=True)` + a fixed scripted bus → bit-for-bit
reproducible cognitive trajectories) was built specifically to enable a
*controlled* ablation of it. Today, however, the only thing that touches the
layer at run time is the passive `CoherenceObserver`, which records PLV while
the entity runs live. There is no controlled, on-vs-off runner: nothing that
holds the seed and the input fixed and toggles *only* the coherence layer to
measure whether it actually changes selection.

That is exactly the experiment the keystone was built for. Without it the
paper's claim that oscillatory phase coherence modulates global-workspace
selection (KAINE_Paper §9) rests on a passive recording and a unit-level
positive control, not on a head-to-head trajectory comparison under identical
conditions. This change builds the controlled ablation runner.

## What Changes

A new **offline** runner executes the cognitive cycle twice under identical
conditions — same `set_global_seed(seed)`, same fixed scripted stimulus, same
`deterministic=True` mode — differing in exactly one thing:

- the **enabled** arm constructs a real `CoherenceScorer` (configurable
  precision gain via `coherence_floor`/`coherence_ceiling`) and feeds the cycle
  scripted per-module phases, with phase-locked and desynchronized coalitions;
- the **disabled** arm passes `coherence=None` (the bit-for-bit layer-absent
  baseline proven in `tests/test_syneidesis_coherence.py`).

Because deterministic mode + the same seed + the same scripted input make a run
bit-for-bit reproducible, the *only* difference between the two arms is the
coherence layer, so **any** trajectory difference is attributable to precision
modulation alone. That is the whole point of the design.

The runner:

- builds a fixed, reproducible scripted stimulus — a deterministic sequence of
  bus events across the prediction/cognition streams, crafted so that
  phase-locked sources carry *lower* raw salience than desynchronized
  competitors, so an effective coherence layer can re-rank them (reusing the
  `ScriptedBus` pattern from the determinism keystone);
- captures per-tick trajectories (selected coalition, salience scores,
  inhibition) for each arm;
- computes an **effect metric** (below) and emits a shared-schema `Verdict`:
  **WIN** when the layer measurably changes selection above a floor, **NULL**
  otherwise, with the effect size in `metrics`;
- writes a seeded JSONL result plus a manifest-ish summary.

It is OFFLINE: it drives only the engine + Syneidesis + Volition over a scripted
in-memory bus. No live modules, no entity boot, no network — the same posture as
the active-inference benchmark.

### Effect metric

The headline effect is the **selection-divergence fraction**: the fraction of
experiential ticks on which the top-ranked selected coalition entry (its
`entry_id`/`source`/`type`) differs between the enabled and disabled arms. It is
complemented by a **mean salience-ranking divergence** (mean normalized
Spearman footrule distance between the two arms' per-tick salience rankings) so
that re-ordering below the top entry is still measured even when the winner is
unchanged. Both are in `[0, 1]`; both are exactly 0 iff the layer made no
difference to selection, which is precisely the property a verdict should turn
on. The verdict is WIN when the selection-divergence fraction exceeds a
configurable floor (default 0), proving the toggle is *connected* and *has an
effect*; NULL otherwise.

## Capabilities

### Modified Capabilities

- `oscillatory-binding`: ADD a controlled, offline oscillatory-ablation runner
  that executes the cycle layer-enabled vs layer-disabled under the same seed and
  scripted input in deterministic mode and emits a WIN/NULL verdict with the
  measured effect of precision modulation on selection.

## Impact

- **Code (new):**
  - `kaine/evaluation/benchmarks/oscillatory_ablation/__init__.py`
  - `.../stimulus.py` — the fixed scripted stimulus + scripted phase registry
    (phase-locked vs desynchronized sources).
  - `.../runner.py` — the two-arm controlled runner + effect metric + verdict.
  - `.../__main__.py` — CLI (`--seed`, `--ticks`, `--out`, gain knobs).
- **Code (touch):** none of the cycle/workspace internals change; the runner
  reuses `CognitiveCycle(deterministic=True, collect_phases=True)`,
  `Syneidesis(coherence=...)`, `set_global_seed`, and the shared `Verdict`.
  `kaine.evaluation` importing `kaine.cycle`/`kaine.workspace` is allowed by the
  sidecar boundary (only CORE importing `kaine.evaluation` is forbidden).
- **Docs:** a short `docs/processes/oscillatory-ablation.md` page: how to run it,
  what WIN/NULL mean, and the determinism guarantee that makes the difference
  attributable to the layer alone.
- **Tests:** seeded run reproduces its verdict + metrics (run twice, identical);
  a crafted stimulus yields a measurable effect (WIN, effect > 0); the disabled
  arm is bit-for-bit the layer-absent baseline; offline / no-boot assertion.
- **Safety:** offline research instrument; read-only w.r.t. any running entity;
  enables no module, boots no entity, opens no network connection.

## Limitations

The scripted stimulus is synthetic, not live perception: it exercises the
selection + coherence machinery under controlled phase schedules, not the full
multi-module dynamics of a booted entity. It proves the *mechanism* (the layer
is connected and changes selection in a controlled setting) and quantifies its
effect there; it does not claim a magnitude for live operation. That is the
correct scope for an offline ablation and mirrors the active-inference
benchmark's synthetic-POMDP posture.
