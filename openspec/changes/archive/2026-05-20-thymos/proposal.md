## Why

`docs/kaine-paper.md` §3.3 puts Thymos as the affect/drive module —
"the body that the rest of the architecture is embodied in" — and
build prompt §4.1 expands it into three levels (dimensional, Scherer
appraisal, regulation), four drive states (curiosity, boredom, social
drive, restlessness), plus a simple goal representation. Phase 4 is a
single-module phase that closes with `v0.4-motivation`.

Phase 4 unlocks two latent integration points from earlier phases:
Syneidesis already exposes a `ThymosModulator` protocol (Phase 1.3)
that returns a multiplier in the salience product but defaults to
1.0; Mnemos already exposes an `EmotionalRetriggerHook` (Phase 3.2)
defaulting to no-op. Thymos plugs into both so the architecture starts
to feed back on itself — affect biases salience biases attention biases
what enters memory biases what triggers recall biases affect.

## What Changes

- Introduce `kaine.modules.thymos` split across files:
  - `state.py` — `DimensionalState` dataclass (`valence`, `arousal`,
    `dominance` ∈ `[-1, 1]^3` with separate `[0, 1]` arousal range);
    homeostatic drift toward configurable baseline per step.
    Damasio-grounded somatic-marker style.
  - `appraisal.py` — Scherer Component Process Model v1: five sequential
    `Check` callables (novelty, intrinsic_pleasantness,
    goal_significance, coping_potential, norm_compatibility) each
    returning a score in `[-1, 1]`. The result tuple maps to a
    `CategoricalEmotion` via a lookup table (joy, sadness, anger,
    fear, surprise, disgust, neutral). Pure functions — testable in
    isolation.
  - `drives.py` — `DriveState` dataclass with the four drives, each
    a value in `[0, 1]` plus its build rate and decay rate. `tick(dt,
    activity)` updates each drive given the elapsed time and the
    current activity signal. Drives exceeding their threshold publish
    `thymos.drive` events that influence Syneidesis salience.
  - `goals.py` — `Goal` dataclass + `GoalLedger` with `add`,
    `complete`, `abandon`, and `relevance(event)` which the Scherer
    `goal_significance` check consumes.
  - `regulation.py` — `RegulationPolicy` protocol + `PassiveDecay`
    default. Phase 4 ships only passive decay (per build prompt: "RL
    policy hook, passive drift only for now").
  - `modulator.py` — `ThymosModulator` (Syneidesis-side protocol)
    implementation that maps current `DimensionalState` to a salience
    multiplier so anxious / aroused states broaden attention and
    depleted / low-valence states narrow it.
  - `module.py` — `Thymos(BaseModule)`. Subscribes to `soma.out`
    (wellness feeds homeostatic drift), `chronos.out`
    (time_since_last_interaction feeds social drive),
    `mnemos.out` (recall affect summary nudges state),
    `workspace.broadcast` (runs Scherer appraisal once per broadcast).
    Periodic state publishing on its own clock.
- Soma already publishes `wellness` and metrics; no Soma change. Chronos
  already publishes `time_since_last_interaction_s`; no Chronos change.
  Mnemos already publishes `mnemos.recall` events with
  `max_affect_intensity` — Thymos picks them up.
- `[thymos]` block in `config/kaine.toml`: baselines, decay rates,
  drive build rates, drive thresholds, appraisal weights, modulator
  curve params, publish intervals. `modules.thymos = false`.
- Tests use pure-function entry points where possible. The module
  test exercises bus integration end-to-end on fakeredis.

## Capabilities

### New Capabilities

- `thymos`: affect + drives + goals + regulation hook. Owns the
  dimensional state, the Scherer CPM five-check appraisal, the four
  drive accumulators, the goal ledger, and the salience modulator
  exposed to Syneidesis.

### Modified Capabilities

None — Thymos plugs into existing protocols (Syneidesis's
`ThymosModulator`, Mnemos's `EmotionalRetriggerHook`) that already
exist; no spec change to those modules.

## Impact

- **Depends on:** `event-bus`, `module-pattern`, `cognitive-cycle`,
  `syneidesis`, `soma`, `chronos`, `mnemos`. All shipped.
- **Repo:** adds `kaine/modules/thymos/*.py`, `tests/test_thymos_*`,
  updates `pyproject.toml` (packages list), `config/kaine.toml`.
- **No new external deps.** Pure Python, deterministic, fast.
- **No runtime impact** on the cycle. Thymos is registered in code
  paths but not auto-added to ModuleRegistry; first boot decides.

After this change Phase 4 closes and `v0.4-motivation` is tagged.
