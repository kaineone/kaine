## Why

Nous runs on pymdp 1.0, which runs on JAX. JAX has no wheels for Termux or 32-bit ARM, so Nous cannot run on the Pixel 6a or smaller boards, and the portability program's target of a full entity on those hosts fails at Nous (phase 3). The engine's arithmetic is small: four factors of at most four states, four actions, horizon 1 by default. NumPy handles it easily.

## What Changes

- **A NumPy engine** (`NumpyActiveInferenceEngine`) that reproduces what `PymdpEngine` computes, for the same generative model:
  - state inference by fixed-point iteration;
  - expected free energy per policy (utility against raw preferences, state information gain, and parameter information gain when the model learns);
  - policy enumeration;
  - Dirichlet learning of action-dependent transitions;
  - carrying the prior forward;
  - the evidence cap, the fixed action factor, preservation of the learned model, and the timeout and error paths.
- **A backend key.** `[nous].backend` selects `"pymdp"` (default) or `"numpy"`. The JAX engine stays the default where JAX is installed. Edge profiles and hosts without JAX use `"numpy"`.
- **Parity is proven against the JAX engine**, not asserted.
  - Golden fixtures recorded from `PymdpEngine` are committed as JSON: learning trajectories on the live model, and policy EFE on the benchmark's multi-factor task models.
  - The NumPy engine must reproduce posteriors, per-policy EFE, chosen actions and learned `pB` within 1e-4.
  - The fixtures are compared on every host, including hosts without JAX.
- **Learned state is interchangeable.** A being preserved on a JAX host can be revived on a NumPy host, and the other way round.
- **The rest of the stack becomes backend-aware:** the extras check (`reasoning` is needed only for pymdp), the Nexus health probe, and the install planner's Termux path.

## Capabilities

### Modified Capabilities
- `nous-active-inference`: a JAX-free engine that computes what the pymdp engine computes, selectable per host, with portable learned state.

## Impact

- New: `kaine/modules/nous/numpy_engine.py`, `scripts/record_nous_golden.py`, `tests/fixtures/nous_golden/*.json`, tests.
- Changed: `kaine/boot.py` (`make_nous` backend), `kaine/extras.py`, `kaine/nexus/health/probes.py`, `config/kaine.toml`, `config/profiles/tier0.toml` and `tier1.toml`, docs, and the portability entries in `kaine/install_target.py`.
