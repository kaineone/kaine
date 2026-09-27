## Why

Two places report more than happened.

**Nous's per-action expected free energy is wrong for horizons longer than one step.** `PymdpEngine._infer` takes the policy EFE vector, which has one entry per multi-step *policy* (`actions^horizon` of them), and truncates it to the first `num_actions` entries as if they were one per action. With `horizon > 1` the reported EFE per action, and the action chosen from it, come from an arbitrary slice of policies. The `nous.policy` event also always reports `horizon: 1`, whatever the configured horizon.

**A world model that does not learn can satisfy the birth gate.** The maturation gate counts Phantasia's `successful_training_passes` as world-model consolidation evidence. Phantasia increments the count after any pass with steps > 0. The fake/EMA world model's `train()` computes a loss but updates nothing, yet it returns `steps = n`. A being whose Phantasia runs the fake backend would therefore show "consolidation" it never did, and could be born on it. That is a pretend process, which the project does not allow.

## What Changes

- **Nous.**
  - The EFE of an action is the best (lowest) EFE among the policies that start with that action, and the chosen action is the first action of the best policy.
  - `nous.policy` reports the configured horizon.
  - At horizon 1 nothing changes.
- **Phantasia.**
  - `TrainOutcome` gains `learned: bool`, true only when the pass updated learned parameters.
  - The DreamerV3 world model reports `learned=True` after a successful update. The fake world model reports `learned=False`.
  - `successful_training_passes`, and the weight save after training, count only learned passes.
  - With the fake backend the gate's consolidation condition is never met, which is honest: that being has not consolidated anything.

## Capabilities

### Modified Capabilities
- `nous-active-inference`: per-action EFE and action choice are correct at any horizon; the published horizon is the real one.
- `phantasia`: only a pass that updated learned parameters counts as consolidation.

## Impact

- `kaine/modules/nous/engine.py`, `kaine/modules/nous/module.py`, `kaine/modules/phantasia/world_model.py`, `kaine/modules/phantasia/module.py`, tests.
- No change for the shipped configuration: horizon 1, and DreamerV3 when Phantasia trains.
