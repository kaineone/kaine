## Why

Soma is KAINE's interoceptive organ. It monitors the compute substrate as a body, accumulates fatigue and regulates homeostasis, and it predicts "how the body feels next" with a `SubstrateForwardModel`: a frozen CfC reservoir feeding an online-adapting linear readout that predicts the next interoceptive feature vector. Its input is a short vector of normalised substrate metrics (CPU, RAM, cycle latency, GPU temperature, padded to 8), which maps cleanly onto stimulation, and a temporal forward model is the kind of work a culture does well. There is also a fitting symmetry in a silicon body feeling itself through living tissue.

kaine now accepts a replacement through the `soma.forward_model` seam (kaine PR #172), so the conversion is pure injection, as it was for Chronos.

## What Changes

- **`WetwareInteroceptiveModel`** (`kaine_cl1/backends/soma.py`) implements the interface Soma calls on its forward model: `step`, `prediction_error_to_salience`, `suspended`, `adaptation_steps`, `state_dict`, `load_state_dict`, plus `reset`, `feature_dim` and `units`.
- **The substrate replaces the frozen reservoir.** Each step population-codes the feature vector onto the Soma territory (the existing `PopulationEncoder`, amplitude-coded, as Chronos does), runs one substrate tick, and decodes the territory's firing rates into the hidden state.
- **The readout stays silicon.** A NumPy linear readout (`units` to `feature_dim`) predicts the next feature vector from that hidden state and adapts by SGD, as the silicon readout does. Prediction error is the same L2 distance in feature space, so Soma's salience normalisation, fatigue and developmental warm-up read it unchanged, and `adaptation_steps` keeps its meaning (one per real readout update).
- **Suspension.** While `suspended` is true (Hypnos offline cycles) the readout does not adapt and `adaptation_steps` does not advance. The substrate still ticks, because the body is still felt during sleep.
- **Snapshots.** `state_dict` holds the readout weights. `load_state_dict` rejects weights of the wrong shape with `ValueError`; Soma catches that, logs it and keeps fresh weights, so a silicon snapshot never loads into the wetware model or the reverse.
- **Plugin wiring.** `WETWARE_BACKENDS` gains `soma` (injected through `forward_model`), so `[plugins.cl1.backends] soma = "cl1"` with a `soma` territory converts Soma.
- `predict()` (a side-effect-free peek) is not provided: stimulating tissue is never side-effect-free, and Soma does not call it.

Earlier drafts decoded surprise directly from firing-rate deviation. That produced an error in different units from the silicon model, which would have broken Soma's salience normalisation and the warm-up's sample count, so the readout design replaces it.

## Non-goals

- Changing Soma's homeostatic policy, fatigue math or event schema.
- Metric collection (stays host-side).
- Real hardware (the plugin is simulator-only).
- A shared cognitive tick across converted modules. Each converted module's step advances the shared substrate timeline by one tick window and reads only its own territory. Chronos (workspace cadence) and Soma (its own sampling interval) run at different rates, so there is no single tick to share yet.

## Impact

- New code: `kaine_cl1/backends/soma.py`; `kaine_cl1/boot.py` (one table entry); `kaine_cl1/plugin.py` (Soma leaves the pending list).
- Tests: backend on the simulator, plugin wiring, and Soma booted through kaine's loader.
