## Why

During Soma's developmental warm-up, the fatigue accumulator's input is damped by subtracting a "warming baseline", the typical recent error, so that cold-start model ignorance does not build sleep pressure while a genuine spike still does. Since `soma-expected-error`, the accumulator integrates the **unexpected** error `U_t` (error beyond each channel's learned band), but the warming baseline is still the mean of the **raw** prediction-error window. The two are different quantities, and the raw mean is usually much larger than `U_t`, so during warm-up the damped input is almost always zero: a spike contributes only when its unexpected part exceeds the mean raw error. The damping no longer does what it was designed to do. The mathematics review of 2026-10-08 found this.

## What Changes

- **Like with like.** Soma keeps a rolling window of the accumulator's own input quantity (`U_t`, or the raw error while a hard threshold is breached), and the warming baseline is the mean of that window before the current tick. The damped input during warm-up is `max(0, action_error - baseline)`, as designed.
- The raw window keeps its other uses (Soma salience and the error-stabilisation guard), unchanged.

## Capabilities

### Modified Capabilities

- `soma-predictive`: the warming baseline is computed from the accumulator's input quantity.

## Impact

- **Code:** `kaine/modules/soma/module.py`.
- **Behaviour:** during warm-up, spikes in unexpected error above its own recent level now build fatigue, as designed; cold-start ignorance is still stripped. Sleep may come slightly earlier in the first 20 minutes of a boot. Outside warm-up nothing changes.
- **Docs:** `docs/09-modules/soma.md`.
