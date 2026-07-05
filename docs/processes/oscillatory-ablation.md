# Oscillatory ablation (coherence layer ENABLED vs DISABLED)

A **controlled, offline** research instrument that measures whether the
oscillatory coherence layer (KAINE_Paper §9) actually changes global-workspace
selection. It runs the cognitive cycle twice under identical conditions and
toggles **only** the coherence layer, then emits a WIN / NULL / NEGATIVE
verdict with the measured effect of precision modulation on selection.

This is the experiment the determinism keystone
(`CognitiveCycle(deterministic=True)` over a scripted bus) was built to enable.
Until now the only thing that touched the layer at run time was the passive
`CoherenceObserver`, which records phase-locking while the entity runs live —
there was no controlled on-vs-off comparison.

The runner is headless and synthetic. It drives only the cycle engine and
Syneidesis over a scripted in-memory bus. It does **not** boot an entity, attach
to live modules, start a real bus connection, or open a network connection.

## The determinism guarantee (why the difference is the layer)

Both arms run with:

- the **same** `set_global_seed(seed)`,
- the **same** fixed scripted stimulus, and
- `deterministic=True` (logical timestamps, canonical within-tick ordering).

Under those conditions a run is bit-for-bit reproducible. The arms differ in
exactly one thing: the **enabled** arm carries a real `CoherenceScorer` (with a
configurable precision gain `[coherence_floor, coherence_ceiling]`); the
**disabled** arm passes `coherence=None` — the layer-absent baseline that
`tests/test_syneidesis_coherence.py` proves is bit-for-bit identical to the
pre-change selection. Therefore **any** difference between the two trajectories
is attributable to the coherence layer alone. That is the whole point.

A test asserts the disabled arm is bit-for-bit equal to an independently-built
layer-absent cycle, so "only the layer differs" is verified, not assumed.

## The scripted stimulus

Four sources emit one event per tick. Two are **phase-locked** (`lock_a`,
`lock_b`, sharing one phase schedule, PLV → 1) and carry **lower** raw salience
(0.40); two are **desynchronized** (`drift_a`, `drift_b`, incommensurate phase
schedules, low PLV) and carry **higher** raw salience (0.60).

With the layer **absent**, the higher-raw-salience drift sources rank first on
every tick. With the layer **enabled**, the phase-locking-value sliding windows
fill over the first several ticks; once they do, the desynchronized sources'
coherence factor collapses toward the floor while the phase-locked sources' rises
toward the ceiling — so a phase-locked source overtakes a drift source. The
selected coalition re-ranks: a controlled, measurable effect of precision
modulation.

## Effect metric and verdict

- **`selection_divergence_fraction`** — fraction of ticks on which the top
  selected entry differs between the enabled and disabled arms. Exactly 0 iff
  the layer never changed the winner.
- **`mean_ranking_divergence`** — mean normalized Spearman footrule distance
  between the two arms' per-tick salience rankings (captures re-ordering below
  the top entry).
- **`coherence_alignment_delta`** — the *directional* metric: the fraction of
  ticks on which the enabled arm's top source is phase-coherent (a
  hypothesized target, from the battery's ground-truth coherent-source set)
  minus the same fraction for the disabled arm. Positive means enabling the
  layer moved selection TOWARD coherent coalitions (the hypothesized
  direction); negative means it moved AWAY (an adverse result). It requires a
  battery with a ground-truth coherent set and is 0 (undefined) on the neutral
  battery.

The verdict model is **three-way** (WIN / NULL / NEGATIVE — all reachable, not
just WIN/NULL):

- **NULL** — `selection_divergence_fraction` is at or below `--min-effect`: the
  layer makes no meaningful change to selection on this stimulus (e.g. the
  neutral battery, which has no coherence structure to exploit). Justifies
  removing the layer.
- **NEGATIVE** — the change is meaningful (above `--min-effect`) but adverse:
  `coherence_alignment_delta` is at or below `-min_alignment`, i.e. the layer
  re-ranks selection AWAY from the coherent coalition, contradicting the
  hypothesis.
- **WIN** — the change is meaningful AND not adverse (on the engineered
  battery: it promotes the phase-locked coalition).

All three are first-class, reportable outcomes, not harness failures. A
correctly-labeled battery (coherence label matches phase reality) can only
ever return WIN or NULL — the coherence layer is strictly monotone in PLV, so
it can only push more-phase-locked sources up. NEGATIVE is reachable only
through the `mislabeled` adversarial battery (see below), which is what makes
it a genuine label/reality-mismatch probe rather than a hand-fed classifier
input.

## The `mislabeled` adversarial battery

`--stimulus mislabeled` runs a battery (`MISLABELED_STIMULUS`) where the
`coherent=True` ground-truth label is put on a high-salience source that is
NOT the most phase-locked (a decoy), while the truly synchronized source is
labeled `coherent=False`. The honest coherence layer still promotes the
truly-synchronized (labeled-False) source over the labeled-coherent decoy,
which yields a genuinely negative `coherence_alignment_delta` computed through
the real pipeline. This is what specifically probes a LABEL/REALITY MISMATCH —
the layer tracking a coherence the ground-truth label disagrees with (e.g. a
mis-specified coalition) — the "the layer is tracking the wrong thing" failure
mode the paper must be able to report.

## Running it

```
python -m kaine.evaluation.benchmarks.oscillatory_ablation \
    --seed 1234 --ticks 16 \
    --coherence-floor 0.05 --coherence-ceiling 8.0 --plv-window 12 \
    --min-effect 0.10 --stimulus engineered \
    --out data/evaluation/benchmarks/oscillatory_ablation.jsonl
```

`--min-effect` (default `0.10`) is the selection-divergence threshold at or
below which the verdict is NULL. `--stimulus` selects the battery and accepts
`engineered` (positive control, default), `neutral` (no coherence contrast),
or `mislabeled` (the adversarial label/reality-mismatch battery above).

The same seed reproduces the verdict and the effect metrics exactly (only the
wall-clock `ts` field differs between runs; it is not part of the cognitive
result). The CLI prints a summary stating the verdict (WIN, NULL, or NEGATIVE)
plainly and writes a seeded JSONL record (per-arm trajectory digest, effect,
verdict).

## Limitation

The scripted stimulus is **synthetic**, not live perception. It exercises the
selection + coherence machinery under controlled phase schedules, not the full
multi-module dynamics of a booted entity. It proves the *mechanism* — the layer
is connected and measurably re-ranks selection in a controlled setting — and
quantifies its effect there; it does not claim a magnitude for live operation.
That is the correct scope for an offline ablation, mirroring the
active-inference benchmark's synthetic-POMDP posture.
