## Context

`PymdpEngine` builds `pymdp.agent.Agent` from a `GenerativeModel`. The model has:
- `A`, `B`, `C` and `D`;
- optional `pB` and `B_action_dependencies`;
- `A_dependencies`, `num_states`, `num_obs` and actions.

pymdp 1.0 does the following:
- **Inference:** fixed-point iteration (FPI) state inference with `num_iter` iterations.
- **Planning:** policy enumeration over the control factor, and expected free energy per policy. That is utility `Σ qo·C` with raw `C`, state information gain `H[qo] − qs·H[A]`, and, when the model learns, parameter information gain from `pB` (`calc_negative_pB_info_gain`, using `spm_wnorm`).
- **Learning:** Dirichlet learning of `B` from the joint of consecutive posteriors under the action taken (`update_state_transition_dirichlet`).
- **Prior propagation:** `update_empirical_prior`.

The benchmark's task models use multi-factor `A_dependencies`, for example `[[0, 1]] * 3`, and horizon 4.

## Decisions

### Scope of the NumPy engine
- **Model features.** It supports exactly the features KAINE's models use:
  - `A_dependencies` over any subset of factors, contracted with `numpy.einsum`;
  - `B` depending on the factor itself and on a single control factor (`B_action_dependencies`);
  - any horizon;
  - `use_utility`, `use_states_info_gain` and `use_param_info_gain`;
  - `learn_B` only.
- **Unsupported features fail at construction:** `learn_A`, inductive inference, or other inference algorithms raise `ValueError`.
- **Arithmetic.** It computes in float64 and reports float lists, as `PymdpEngine` does.
- **FPI** follows pymdp's parallel (Jacobi) update from `log q = 0`: at each iteration, the log-likelihood marginal for each factor, plus the log of the prior (with pymdp's `log_stable` epsilon), then a softmax. Same `num_iter`.
- **Policies** are enumerated in the same order as pymdp's `construct_policies`, and the per-action EFE aggregation (the best policy starting with each action) is shared with `PymdpEngine`.
- **Learning** reproduces `update_state_transition_dirichlet` for one step:
  - `pB[f][:, :, u] += lr · outer(q_t[f], q_{t−1}[f])` for the taken action `u`;
  - then `B = normalised pB`;
  - the action factor is restored, and the evidence cap is applied as in `PymdpEngine`.
- **State interchange.** `learned_state()` and `load_learned_state()` use the same JSON shape as `PymdpEngine`, so preservation bundles are interchangeable.

### The seam
- `make_nous` reads `[nous].backend`:
  - `"pymdp"`, the default, builds `PymdpEngine`;
  - `"numpy"` builds `NumpyActiveInferenceEngine`;
  - anything else is a configuration error.
- The two engines share the `ActiveInferenceEngine` protocol and the timeout guard. The guard moves into a small shared base, so both engines run the same executor, deadline, error handling and generation logic.
- The benchmark adapter (`aif_agent.py`) keeps using `PymdpEngine`. Moving it to a backend-neutral planning API is a follow-up.

### Golden fixtures
- **Recording.** `scripts/record_nous_golden.py` runs only where pymdp and JAX are installed. It records:
  1. 60 steps of the live model on a fixed observation sequence: each step's observation, posterior, per-policy negative EFE, chosen action, and `pB` after learning;
  2. the benchmark exploitation and T-maze models: per-policy negative EFE for 20 fixed belief states;
  3. the live model at horizon 2: a 10-step trajectory.
- **Storage.** The fixtures are committed JSON, a few hundred KB, under `tests/fixtures/nous_golden/`, with the pymdp version recorded. Re-recording is a deliberate operator step.
- **Tolerance.** The NumPy engine must match within `atol = 1e-4`: JAX runs in float32 while NumPy runs in float64, and learning compounds small differences over 60 steps. Chosen actions must match exactly.

## Risks
- **Hidden pymdp behaviour.** pymdp details such as its epsilon and normalisation may differ from a reading of the source. The fixtures are the arbiter.
- **Version drift.** If a pymdp release changes its numerics, the fixtures are re-recorded and the change is reviewed.
- **Performance.** At horizon 4 the benchmark enumerates 256 policies. NumPy is fast enough offline. The live model at horizon 1 has 4 policies.
