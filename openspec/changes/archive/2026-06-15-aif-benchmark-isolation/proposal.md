# aif-benchmark-isolation

## Why

The AIF-vs-RL benchmark's methodology (design.md, the runner docstring) claims a
**matched-information** comparison: both arms see the same environment and the same
reward, and the AIF preference `C` encodes the *same* reward the RL baseline
optimises. That confound-isolation is the load-bearing fairness property — if one
arm silently received a different env or reward, any verdict would be meaningless.

Today nothing in the test suite asserts it. The fast tests check env tensors,
the RL baseline, and the verdict classifier; the opt-in real-pymdp tests check
the AIF arm exercises real active inference. None proves the two arms are driven
by a matched environment. This change adds that isolation test so a future
confound (one arm wired to a different env/reward) would fail loudly.

## What Changes

- Add `kaine/evaluation/benchmarks/active_inference/isolation.py`: a small honest
  accessor `arm_environment_fingerprint(task)` that captures *what env/reward each
  arm receives* from a task — for the RL arm: observation-space size
  (`rl_num_obs`), action count, `reward_matching()`, `optimal_return()`; for the
  AIF arm: the generative-model the adapter builds (`build_model_for_env`) and its
  preference `C`, plus the same `reward_matching()` / `optimal_return()`. It only
  reads the task; it changes no benchmark behaviour.
- Add `tests/test_aif_benchmark_isolation.py`: for each task in the default suite
  at a fixed seed, assert both arms share the same env definition — identical
  reward structure (`reward_matching`, reward matrices, `optimal_return`), and
  that the AIF preference `C` encodes the same reward the RL baseline optimises
  (the win/lose magnitudes the env's reward-obs modality exposes).

## Scope and honesty note

The two arms take *different actions*, so their realised observation **streams**
can never be byte-identical — that is expected and is not the invariant. The
correct, testable invariant (and what this change asserts) is that both arms are
constructed from the **same env definition**: same task/env class, same reward
function/matrices, same observation space for a given seed, and an AIF `C` derived
from the same reward the RL agent sees. A failing version of this test would catch
a future change where one arm is silently handed a different env or reward.
