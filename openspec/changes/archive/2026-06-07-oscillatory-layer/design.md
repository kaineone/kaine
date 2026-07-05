# Design — Oscillatory binding layer

## Where it plugs in

Two seams, both already mapped:
- `BaseModule` (`kaine/modules/base.py`) — gains an optional `ModuleOscillator`
  and a `phase()` accessor. Modules with no oscillator report a neutral phase.
- The salience path (`kaine/workspace/salience.py` `RuleBasedSalience.score` →
  `kaine/workspace/syneidesis.py` `select`) — gains a coherence multiplier applied
  to the coalition's aggregate, computed in a new `kaine/workspace/coherence.py`.

## The oscillator

A `ModuleOscillator` holds a small snnTorch LIF population (CPU). Each tick the
module injects a drive proportional to its recent activity (publish rate /
salience); the population's spiking produces a rhythm whose **phase** we estimate
(e.g., Hilbert/segment phase over a short spike-rate window). The phase is the
only thing exposed upward — cheap and serializable.

## Coherence = phase-locking value

`coherence.py` computes the pairwise **PLV** between the modules contributing to a
candidate coalition over a `plv_window` of recent phases. PLV ∈ [0,1]: 1 = locked,
0 = independent. The coalition coherence factor maps mean PLV into
`[coherence_floor, coherence_ceiling]` (e.g., floor 0.8 attenuates desynchronized
coalitions, ceiling 1.25 boosts locked ones). The factor multiplies the coalition
aggregate before top-k/threshold.

## Additive and flagged

When `[oscillator].enabled` is false the factor is exactly 1.0 — selection is
bit-for-bit the current behavior. This lets the change land, ship the sidecar
observer, and tune floor/ceiling against recorded coherence before enabling it in
the live loop. The paper calls this layer empirically uncharacterized; the flag is
how we characterize it safely.

## Why late in the roadmap

It touches BaseModule and the scorer — i.e., everything. Landing it after the new
modules exist means every module (including Empatheia/Phantasia/pymdp-Nous) gets
an oscillator uniformly, and the PLV has a full module set to bind across.

## Risks

- Cost per tick → small populations, short windows, top-k=5 keeps PLV trivial;
  phase estimation vectorized.
- Pathological coherence (correlated-error coalitions self-reinforcing, paper §9)
  → bounded multiplier + the sidecar's anomalous-coherence detection.
- snnTorch availability → optional extra; oscillator absent ⇒ neutral phase ⇒
  factor 1.0.

## v1 co-activity proxy and v2 direction

v1 drives each module's LIF oscillator from **co-activity** (its publish rate /
salience), which is a proxy for the paper's content-relatedness. Two modules
publishing frequently are likely processing something related — but this is
indirect. **Limitation:** two unrelated high-salience modules could spuriously
phase-lock under high load.

**v2 sketch (out of scope here):** drive LIF input current from
**prediction-error magnitude** — the signed surprise from each module's forward
model (`soma-forward-model-fatigue`, `nous-pymdp-swap`, `chronos-forward-model`,
etc.). Modules surprised by the same event will spike together; modules in steady
state will not. This makes synchrony semantically grounded in shared prediction
failure rather than correlated activity.

## Oscillator/PLV serialization

`ModuleOscillator` state (membrane voltages, spike history, phase buffer) SHALL be
serializable to a dict for checkpoint/resume. PLV sliding-window buffers are
ephemeral and are not persisted across restarts (they re-initialize to neutral).

## set_frequency hook

`ModuleOscillator.set_frequency(scale: float)` multiplies the drive injection
magnitude by `scale`, effectively slowing the oscillator's rhythm. Called by
`hypnos-fatigue-phases` phase 1 at maintenance entry. `FakeOscillator` ignores
the call (deterministic phase for tests).

## Out of scope

A learned Syneidesis with ignition/phase-transition dynamics (paper §10).
Gamma-band biological realism beyond phase-locking.
