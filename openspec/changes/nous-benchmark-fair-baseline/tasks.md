## 1. Fair baseline and sampled policies

- [x] 1.1 `QLearningConfig.memory: int | None = None` (None = task horizon, 0 = memoryless); the Q-table is a dict keyed by the tuple of the last `memory + 1` observation keys of the episode; `as_dict` records `memory`.
- [x] 1.2 `AIFAgent(task, ..., rng=None)`: with a generator, sample the policy from pymdp's `q_pi` (renormalised); without, argmin as now. The runner gives each evaluation seed its own generator derived from the seed.
- [x] 1.3 Tests: a history-keyed learner can represent the cue (two histories differing only in the cue observation map to different Q rows); `memory=0` reproduces the old key; sampled AIF runs reproduce under a seed and differ across seeds when the posterior is not one-hot; argmin without a generator; mutation-check.
- [x] 1.4 Docs: `docs/15-experiments/README.md`, `docs/09-modules/nous.md`.
- [x] 1.5 `openspec validate nous-benchmark-fair-baseline --strict`.
