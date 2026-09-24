## Why

Nous is KAINE's reasoning organ: **active-inference** belief updating and policy
selection over a compact discrete generative model (`pymdp`). Active inference is
the free-energy principle, and the free-energy principle is exactly the paradigm
Cortical Labs' cultures are characterised under (DishBrain). Conceptually this is
the **purest** fit of all — the biological substrate minimising surprise in a
closed loop *is* active inference. It is placed after Chronos/Soma/Oscillator
because the hard part — reliably **decoding a discrete policy choice** from
spikes — is a genuine research problem, so it is scoped as convertible but
enabled only once decode is validated.

## What Changes

- Add a `cl1` backend for Nous' generative-model client: population-code the
  current belief over states onto the Nous territory, deliver closed-loop stim as
  incoming evidence, and decode the resulting territory firing balance into a
  policy selection / expected-free-energy signal.
- **Encode:** belief vector → population code (which channels fire encodes the
  distribution); observations → stim as evidence.
- **Decode:** territory firing balance across sub-populations → selected policy;
  criticality/entropy → an expected-free-energy proxy.
- Select via `[backends].nous = "cl1"`; `nous.out` event shapes unchanged.
- Ships **default-off** (`"silicon"`) until the decode acceptance test passes,
  because policy decode reliability is the open risk.

## Non-goals

- Replacing `pymdp`'s semantics or Nous' event schema.
- Claiming biological active inference beats the silicon baseline — the plan only
  requires measurable predictive work, benchmarked against KAINE's existing
  active-inference benchmark.
- Executing on real hardware in this change (the project goal, deferred until
  grant-funded access; validated on the simulator meanwhile).

## Impact

- New capability: `nous-wetware-backend`. Depends on `cl1-substrate`.
- New code: `kaine_cl1/backends/nous.py`; wiring in `kaine_cl1/boot.py`.
- Reuses KAINE's `active-inference-benchmark` as the evaluation harness.
