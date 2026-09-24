## Why

Chronos is KAINE's interval-timing organ: it encodes workspace history with a
small Closed-form Continuous-time (CfC) network and flags temporal anomaly,
rumination, and idle time. It is the **best first conversion**: timing and
sequence anticipation are exactly what recurrent biological cultures do
intrinsically, and the upstream model is tiny and already CPU-pinned, so the
silicon→wetware swap is high-value and low-risk. This is the reference
conversion that proves the `cl1-substrate` pattern end-to-end on the simulator.

## What Changes

- Add a `cl1` backend for Chronos' forward model — `WetwareTimingModel` — that
  satisfies the same client interface the silicon CfC presents to
  `kaine.modules.chronos`, backed by a channel territory on the shared substrate.
- **Encode:** a summary of recent workspace activity → a temporal stimulation
  pattern across the Chronos territory (inter-stimulus timing carries the
  temporal context).
- **Decode:** the territory's spike response in the tick → (predicted-next-interval
  signal, prediction-error). Prediction error is the surprise decoder over the
  response (criticality / Lempel-Ziv relative to the rolling baseline).
- Select via `[backends].chronos = "cl1"`; absent/`"silicon"` = unchanged upstream.
- Chronos' module body, its bus subscriptions, and its `chronos.out` event shapes
  are unchanged.

## Non-goals

- Changing Chronos' cognitive semantics or event schema.
- Executing on real hardware in this change — the goal, but deferred until
  grant-funded access exists; built and validated on the simulator meanwhile.

## Impact

- New capability: `chronos-wetware-backend`. Depends on `cl1-substrate`.
- New code: `kaine_cl1/backends/chronos.py`; wiring in `kaine_cl1/boot.py`.
- If Chronos exposes no `forward_model=` seam upstream, contribute a vendor-neutral
  one (silicon default unchanged) per the isolation policy.
