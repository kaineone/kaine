## Why

KAINE's thesis is that a mind is the competition among **predictive processors**
through a shared workspace, and its processors are already framed in
free-energy / prediction-error terms. Cortical Labs' CL1 realises the *same*
free-energy paradigm in **living cortical neurons** on a 64-channel
multi-electrode array (the DishBrain lineage). That makes a concrete question
answerable: can a KAINE module's *forward model* run on biological tissue instead
of silicon, keeping everything else identical?

Answering it needs one enabling layer before any single module is converted,
because a CL1 system exposes **one culture on one 64-channel array**, and every
converted module has to share it. This change builds that layer: the
`cl1-substrate` capability, and nothing else. It is built and validated on the
**free simulator** (`cl.is_simulator()`), since real CL1 hardware is not yet
available to this project; the same layer will drive real cultures once
running on real tissue becomes a deliberate, reviewed step.

This is strictly downstream: it injects behind KAINE's existing client seams and
never edits pure KAINE (see `docs/downstream-isolation.md`).

## What Changes

- **A single owned substrate session**: one process-wide `cl.open()` connection
  and its simulator configuration (accelerated-time, replay, seed, tick rate),
  owned by the overlay, never opened by individual module backends.
- **A substrate broker**, the one new architectural piece. It leases
  **disjoint channel territories** to converted modules, runs the **single**
  closed loop (`neurons.loop`), delivers each module's queued stim, reads the
  spikes, and routes each module only the spikes on its own channels. It enforces
  the 64-electrode ceiling.
- **Cadence bridging**: the substrate loop (~100 Hz) nests inside KAINE's
  cognitive cycle (~3.3 Hz); the broker aggregates the sub-ticks in one cognitive
  tick into the observation a module backend decodes, and never starves the
  cycle.
- **Reversible codecs**: shared encode (signal → `StimDesign`/`BurstDesign`
  patterns) and decode (spikes → scalar/vector via `cl.analysis`: firing rate,
  criticality/LZ as a **surprise** proxy, functional connectivity) primitives
  that every module conversion composes.
- **A downstream boot**: constructs stock KAINE modules and injects CL1-backed
  forward models through existing seams; where a seam is missing, the policy is
  to upstream a *vendor-neutral* seam, never a CL1-specific edit.
- **Simulator determinism & welfare posture**: reproducible seeded runs; charge
  limits treated as safety limits; no stim reaches a real culture without
  simulator characterisation first.

## Non-goals

- Converting any specific module (that is the per-module changes that depend on
  this one).
- Executing on real CL1 hardware *in this change*. Hardware is the project's
  goal, but real CL1 hardware is not available to this project yet; this
  change delivers the layer that will drive it, validated on the simulator,
  and running on real tissue will be a deliberate, reviewed step (see
  `docs/biological-welfare.md`).
- Any modification to pure KAINE or to `vendor/cl-sdk/`.

## Impact

- New capability: `cl1-substrate`.
- New code: `kaine_cl1/substrate/{session,broker,codec}.py`, `kaine_cl1/boot.py`.
- Unblocks: `chronos-on-wetware`, `soma-on-wetware`, `oscillator-on-wetware`,
  `nous-on-wetware`, `hybrid-wetware-conversions`.
