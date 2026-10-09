## Why

The active-inference benchmark compares Nous's expected-free-energy agent with tabular Q-learning on an epistemic T-maze and an exploitation task. Two properties of the harness decide the comparison before it runs.

- **The baseline cannot remember.** The Q-learner indexes its table by the current observation only. On the T-maze the cue is adjacent only to the centre, and back at the centre the observation is identical to the starting one, so no memoryless policy can carry the cue to an arm: its best expected return is 0, against 0.96 for an agent that keeps beliefs. The T-maze WIN is therefore structural, not evidence that belief and information value help.
- **Policy precision does nothing.** The agent takes the argmin of expected free energy, so the policy precision gamma (16) that active inference uses to turn expected free energy into a policy posterior never affects behaviour.

The mathematics review of 2026-10-08 found both.

## What Changes

- **History-based baseline.** `QLearningConfig.memory` sets how many earlier observations of the current episode the Q-learner's state key includes. The default, `None`, means the whole episode (`task.horizon`), the standard tabular baseline for a finite-horizon partially observable task. `memory=0` keeps the memoryless learner as an explicit control. The Q-table becomes a sparse map keyed by the observation history. The chosen memory is recorded with the hyperparameters.
- **Sampled policies.** Given a generator, `AIFAgent` samples its policy from pymdp's policy posterior `q(pi) = softmax(gamma * (-G) + ln E)`, as pymdp's own `sample_action` does, so gamma shapes behaviour. The runner gives each evaluation seed its own generator derived from the seed, so runs reproduce. Without a generator the agent keeps the argmin, which the parity tests use.
- **The live Nous engine is unchanged.** It keeps deterministic selection, so the recorded golden fixtures stay valid. Making the live engine stochastic is a separate decision.

## Capabilities

### Modified Capabilities

- `active-inference-benchmark`: the baseline's observation memory and the agent's policy sampling.

## Impact

- **Code:** `kaine/evaluation/benchmarks/active_inference/{rl_baseline,aif_agent,runner}.py`.
- **Behaviour:** the benchmark's T-maze verdict is no longer guaranteed; it now measures whether belief-based planning beats a learner with the same information. Earlier benchmark records were produced against the memoryless baseline and stay as they are.
- **Tests:** the slow lane (`tests/test_active_inference_benchmark.py`) runs.
- **Docs:** `docs/15-experiments/README.md`, `docs/09-modules/nous.md`.
- **Paper:** §6.4 describes the baseline.
