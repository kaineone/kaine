# Design — `numpy-cfc`

## Reservoir generation (`kaine/cfc_numpy.py`)

- `ReservoirWeights.generate(seed, input_size, units, backbone_units=128)`: `rng = np.random.default_rng(seed)`. It draws parameters in `ncps` construction order (backbone, ff1, ff2, time_a, time_b):
  - each weight is xavier-uniform, bound √(6/(fan_in+fan_out));
  - each bias is uniform ±1/√fan_in, where fan_in is input+units for the backbone and backbone_units for the heads.
  - Everything is float32.
- `numpy_cfc_step(w, x, h) -> h'`:
  1. `z = concat(x, h)`;
  2. `z = 1.7159·tanh(0.666·(z W_bbᵀ + b_bb))`;
  3. `f1 = tanh(z W_ff1ᵀ + b1)`, `f2 = tanh(z W_ff2ᵀ + b2)`;
  4. `t = sigmoid((z W_taᵀ + b_ta) + (z W_tbᵀ + b_tb))` at ts = 1;
  5. `h' = f1·(1−t) + t·f2`.
- `NumpyReadout(units, out)`: its initial `W` and `b` are drawn from the same seeded generator, after the reservoir, with `nn.Linear`'s default distribution: weight and bias uniform ±1/√units. Both backends use these initial values. From then on the readout is trained and persisted as today. `predict(h)` and `sgd_step(h, target, lr)` use the MSE gradient `(2/D)·e·hᵀ`. A non-finite loss or gradient skips the step, as the torch path does.

## Backends

- Soma's `SubstrateForwardModel` and Chronos's `ChronosNetwork` and `ForwardPredictionHead` gain a `backend` (`numpy` or `torch`).
  - Both backends take their reservoir from `ReservoirWeights.generate(seed, …)`. The torch backend copies the arrays into the `ncps` module's parameters.
  - Only the numpy backend avoids importing torch.
- Construction takes `reservoir_seed`. The modules draw one with `kaine.cfc_numpy.draw_reservoir_seed()` when they start fresh, and restore it on `deserialize`. The draw comes from the process's legacy global NumPy random state, which `kaine.experiment.seeding.set_global_seed` seeds. A seeded experiment therefore reproduces its reservoirs, as it did when torch's global RNG initialised them, and an unseeded process gets a fresh seed from NumPy's entropy-seeded state.
- Every existing behaviour is kept: suspend on sleep, the non-finite guards, `reset()`, parameter counts, the salience mapping, and the `state_dict()` and `load_state_dict()` of the readout.

## Serialisation

- Soma: `{"forward_model": {...readout...}, "reservoir_seed": int}`. Chronos: the same, with `"pred_head"`.
- `deserialize` with a seed rebuilds the reservoir from it before loading the readout.
- `deserialize` without a seed, from an older snapshot, logs `"<module>: snapshot has no reservoir seed; the reservoir is new"` and keeps the fresh one.

## Parity test

- Generate the weights from a seed, then build both backends. Feed 500 steps of deterministic pseudo-random inputs with readout training on. Hidden states, predictions and readout weights must agree to 1e-5 at every step.
- This test needs torch; it is skipped where torch is absent. The numpy-only tests always run.
