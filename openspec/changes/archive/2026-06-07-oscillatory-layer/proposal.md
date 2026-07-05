## Why

`KAINE_Paper_v4.md` §3.2 / contribution 6 add an **oscillatory synchronization
layer**: each module maintains a small spiking population (leaky integrate-and-fire
neurons via snnTorch, CPU); when modules process related content their oscillators
phase-lock; **Syneidesis scores events not only by salience but by the oscillatory
coherence between the producing modules**, applying a synchronization bonus to
phase-locked coalitions and attenuating desynchronized ones. This implements
**binding by synchrony** (Doesburg et al. 2009; Melloni et al. 2007) as the
selection mechanism for conscious access. None of this exists today; salience is a
pure product form with no temporal/coherence term.

This is the most novel and cross-cutting change, and the paper itself flags it as
"empirically uncharacterized" (§9). It is therefore **additive and flagged**: the
coherence multiplier defaults to 1.0 (no behavior change) until enabled.

## What Changes

- `kaine/oscillator/` — a `ModuleOscillator` wrapping a small snnTorch LIF
  population. Each module drives its oscillator from its own activity (publish rate
  / salience) each tick; the oscillator exposes a phase estimate.
- `BaseModule` gains an optional oscillator + a `phase()` accessor; the cycle
  collects per-module phase each tick (lightweight, CPU).
- `kaine/workspace/coherence.py` — pairwise **phase-locking value (PLV)** over a
  sliding window between the modules contributing to a candidate coalition.
- Salience scorer gains a coherence term: a coalition's aggregate salience is
  multiplied by a coherence factor derived from the PLV among its source modules,
  bounded to `[coherence_floor, coherence_ceiling]`. With the layer disabled the
  factor is exactly 1.0.
- `[oscillator]` config: `enabled`, `population_size`, `plv_window`,
  `coherence_floor`, `coherence_ceiling`.

## Capabilities

### New Capabilities

- `oscillatory-binding`: per-module LIF oscillators, PLV computation, and the
  coherence multiplier in Syneidesis salience — additive and disabled by default.

### Modified Capabilities

None expressed as deltas (salience remains a product form; coherence is an
additional bounded multiplier that is 1.0 when disabled).

## Impact

- **Depends on:** `module-pattern` (oscillator hook), `syneidesis`/`cognitive-
  cycle` (phase collection + coherence multiplier). **New dep:** `snnTorch`
  (CPU), optional `[oscillator]` extra.
- **Perf:** small LIF populations on CPU per module; PLV is O(coalition²) over a
  short window — negligible at top-k=5. Phase collection adds a tiny per-tick cost.
- **Risk:** novel; behavior change only when `enabled`. Ship with the sidecar
  coherence observer (`sidecar-observers`) so its effect is measured before
  enabling hot.
- Ships disabled (`[oscillator].enabled = false`).
