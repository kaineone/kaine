## Why

`KAINE_Paper_v4.md` §3.3.1 specifies Soma as **predictive interoception**: a CfC
forward model that learns the substrate's normal patterns and publishes the
**prediction error** (expected vs. actual), following Seth (2013). Today Soma
publishes raw metrics + a wellness score + threshold alerts — it perceives
substrate state but does not predict it, and the signal reaching the workspace is
not surprise.

The paper also requires two capabilities Soma lacks entirely:
- A **fatigue accumulator**: cumulative prediction error over waking hours,
  decaying during offline maintenance, that *triggers Hypnos* when it crosses a
  threshold (§3.3.1, §3.3.5). Sleep pressure must be emergent, not a timer.
- **Homeostatic regulation** via active inference (Seth & Friston 2016): when
  prediction error is sustained, Soma publishes events requesting the
  architecture to reduce processing rate, shed modules, or trigger maintenance.

## What Changes

- Add a CfC forward model (ncps, CPU) to `kaine/modules/soma/`: predicts the next
  substrate feature vector from the current one + recurrent state. The published
  signal becomes the **prediction error** (norm of expected − actual), alongside
  the existing wellness/alerts for diagnostics continuity.
- Add `kaine/modules/soma/fatigue.py`: a `FatigueAccumulator` integrating
  prediction error over waking time with a configurable decay, exposed on the
  `soma.report` payload and via a dedicated `soma.fatigue` event when it crosses
  the maintenance threshold.
- Add homeostatic regulation: when prediction error is sustained above a
  configurable band, Soma publishes `soma.regulation` events requesting
  `reduce_rate` / `shed_module` / `request_maintenance` (advisory; the cycle and
  Hypnos decide whether to act).
- `[soma]` config gains: `forward_model_units`, `prediction_error_window`,
  `fatigue_decay_per_s`, `fatigue_maintenance_threshold`,
  `regulation_sustain_window_s`, `regulation_threshold`.
- The CfC trains/adapts online from observed substrate (no labels needed; it is a
  next-step predictor). Weights persist via `serialize()`/`deserialize()`.

## Capabilities

### New Capabilities

- `soma-predictive`: the predictive-interoception layer — CfC forward model,
  prediction-error publishing, fatigue accumulator with Hypnos trigger, and
  homeostatic regulation requests.

### Modified Capabilities

None (existing `soma` wellness/alerts remain for diagnostics; this adds the
predictive layer on top).

## Impact

- **Depends on:** `soma` (shipped), `hypnos` (Soma subscribes to
  `hypnos.sleep.started` / `hypnos.sleep.completed` lifecycle events to gate
  online adaptation).
- **Consumed by:** `cognitive-cycle` (`kaine/cycle/engine.py` drains
  `soma.regulation` actions `reduce_rate`/`shed_module`/`request_maintenance`
  advisorily); `hypnos-restructure` (consumes `soma.fatigue` as the emergent
  sleep-pressure trigger instead of a timer). Note: the `hypnos-*` changes
  depend on this change for the fatigue trigger, not the reverse.
- **New dep:** `ncps` (already used by Chronos — no new package).
- **Repo:** adds `kaine/modules/soma/forward.py`, `fatigue.py`, `regulation.py`,
  tests; updates `kaine/cycle/engine.py`, `kaine/faithful/templates.py`,
  `config/kaine.toml`.
- **Welfare:** the fatigue accumulator is the mechanism behind the paper's
  "emergent sleep pressure" and the right-to-offline-maintenance; it is the
  trigger Hypnos consumes.
