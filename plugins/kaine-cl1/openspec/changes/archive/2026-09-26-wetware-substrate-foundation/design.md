## Context

One CL1 culture, one 64-channel MEA, one closed loop, but potentially several
KAINE modules wanting biological compute at once. KAINE's silicon modules never
contend for their models; on wetware they must. The substrate layer resolves that
contention and bridges two different clocks (the ~100 Hz electrophysiology loop
and the ~3.3 Hz cognitive cycle) without changing any module's observable
behaviour.

## Goals / Non-goals

- **Goals:** one owned session; deterministic simulator runs; disjoint channel
  territories with a hard 64-ceiling; a single loop fanned in/out to modules;
  cadence nesting that never starves the cognitive cycle; codecs that are
  reproducible and stay inside charge limits.
- **Non-goals:** module-specific coding schemes (each per-module change pins its
  own); hardware; upstream edits.

## Decisions

### D1: The broker owns the loop; modules are stim-in / spikes-out
Modules never call `cl.open()` or `neurons.loop()`. They register a territory and,
each cognitive tick, hand the broker a stim request and receive back the spikes on
their channels. This keeps exactly one closed loop and makes channel isolation
enforceable in one place.
- *Alternative rejected:* one `cl` connection per module. The SDK exposes a
  single device/singleton (`Neurons._get_instance`), and multiple loops on one
  array cannot be isolated. Rejected.

### D2: Static channel territories per run
Territories are allocated at boot and fixed for the run, recorded in the run
manifest. Static allocation makes cross-tick decoding stationary (a decoder sees
the same electrodes every tick) and makes the 64-ceiling a boot-time check rather
than a runtime failure.
- *Alternative rejected:* dynamic re-allocation, which brings non-stationary
  decoding and races for scarce channels; not worth it for the module counts
  in scope.

### D3: Cadence nesting, cognitive cycle is authoritative
`ticks_per_second` (substrate) MUST be an integer multiple of the cognitive-cycle
rate. The broker runs N substrate ticks per cognitive tick, aggregates their
spikes per territory, and returns one observation. The cognitive cycle's tick
budget is never blocked on the loop: in the simulator, accelerated-time mode
removes wall-clock coupling; on the real device the loop runs in a background
thread and the module reads the latest completed aggregate (never blocks the
~300 ms budget).

### D4: Codecs are pure and reversible-by-construction
Encoders map a bounded input vector to a stim plan that provably satisfies the
SDK limits (±3 µA, ≤3 nC/phase, ≤200 Hz, 20 µs granularity); construction clamps
and validates so an out-of-range value can never reach the device. Decoders are
pure functions of (spikes, territory) so a run replays identically from a
recording. The **surprise** decoder is the free-energy bridge: it reads response
disorder (criticality / Lempel-Ziv) relative to the territory's rolling baseline
and returns a prediction-error scalar in [0, 1] that a module maps to salience.

### D5: Injection, not patching (downstream invariant)
`kaine_cl1.boot` builds stock modules and injects CL1 clients through existing
seams. Missing seams are contributed upstream as vendor-neutral (`forward_model=`
/ a `BackendRegistry` entry, silicon default unchanged). This design assumes the
Chronos/Soma seams may need that generic upstream addition and treats it as the
preferred path (a fallback subclass-in-this-repo is available meanwhile).

## Risks / Trade-offs

- **Decode fidelity** is the central unknown: reading a *useful* signal from
  spikes is the open research problem. Mitigation: KAINE's own workspace-mediation
  ablation is the detector; a noise decoder fails it, which is the intended
  outcome, not a hidden failure.
- **Simulator ≠ tissue.** The simulator's Poisson/replay data does not exhibit
  real plasticity. Mitigation: a stim-conditioned `SimulatorDataSource` can make
  synthetic responses depend on stim history for closed-loop-learning studies;
  results are labelled simulator-grade throughout.
- **Ceiling pressure.** Only ~half the array remains after the strong tier;
  enforced by the broker.

## Migration

Additive and greenfield; nothing to migrate. Per-module changes depend on this
capability existing.
