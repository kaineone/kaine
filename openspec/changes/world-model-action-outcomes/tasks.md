## 1. Paper (first)

- [ ] 1.1 Paper change: the action-conditioned transition (§4 and an appendix entry), what counts as the entity's action, the continuity of a preserved entity's model, and whether the action-outcome error is reported and acts can be imagined. Starts only when the start condition in the proposal holds.

## 2. Code (after 1.1)

- [ ] 2.1 The action input in both engines with zero initial weights, the checkpoint format with its migration, and tests that a migrated model predicts exactly as before with zero action input.
- [ ] 2.2 The action streams (realized act intents and motor efference copies) into the world model's observation step, with tests.
- [ ] 2.3 Docs (`docs/09-modules/world-model.md`) and configuration comments.

## 3. Study (after 2)

- [ ] 3.1 A study branch with the world model, the light effector and the pan-tilt camera body together, from the preserved seed, so both action streams condition the transition.
