## Why

The module ignition study turns on Phantasia training and weight persistence in its overlay, because a viewing that loses the learned world model would hand the next viewing a being with a younger world model than the one that watched the films. The study runner does not check that the world model was captured. A step whose preservation reports success but whose bundle holds no Phantasia weights (a non-learning backend, a missing checkpoint, a config drift) is recorded as complete, and the line continues from a lesser being. The umbrella change's task 2.2 requires the runner to refuse such a step.

## What Changes

- When a step's module set includes Phantasia, the runner reads the resulting bundle's loose `manifest.json` and records the step as complete only when `world_model_captured` is true. Otherwise it records `failed:world_model_not_captured` and halts, like any other failed step.
- A bundle whose manifest is missing or unreadable, while Phantasia is enabled, is recorded as `failed:manifest_unreadable`.
- Steps without Phantasia (the gestation and the viewings before Phantasia is added) are unchanged.
- The step record carries `world_model_captured` (true, false, or null when Phantasia is off) so the analysis and the operator can see it.

## Impact

- `kaine/research/ignition_study/runner.py`: the outcome check and the step record.
- `tests/test_ignition_study_runner.py`: the new outcomes.
- No change to preservation, the bundle format or the entity. The manifest is already written loose and unencrypted by `preserve_live`, so the runner never needs the entity's key.
