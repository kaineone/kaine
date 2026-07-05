## 1. Environment fingerprint accessor

- [x] 1.1 Add `kaine/evaluation/benchmarks/active_inference/isolation.py` with
      `arm_environment_fingerprint(task)` capturing the env/reward each arm
      receives (RL: obs-space size, actions, reward_matching, optimal_return;
      AIF: generative model A/B/D + preference C, reward_matching, optimal_return)
- [x] 1.2 Add a helper that extracts the win/lose reward magnitudes the env's
      reward-observation modality exposes (the matched-reward invariant)

## 2. Isolation test

- [x] 2.1 Add `tests/test_aif_benchmark_isolation.py`
- [x] 2.2 For each task in `default_suite()` at a fixed seed, assert both arms
      share identical observation-space size and reward structure
      (`reward_matching`, reward matrices, `optimal_return`)
- [x] 2.3 Assert the AIF preference `C` encodes the same reward magnitudes the
      RL baseline optimises (matched-reward invariant)
- [x] 2.4 Add a negative-control assertion: a tampered task (different reward)
      makes the matched-reward check fail (the test has teeth)

## 3. Spec + validate

- [x] 3.1 Add `active-inference-benchmark` ADDED requirement (matched environment)
- [x] 3.2 `openspec validate aif-benchmark-isolation --strict` passes
- [x] 3.3 Isolation test green (no pymdp/jax extra required — pure task inspection)
