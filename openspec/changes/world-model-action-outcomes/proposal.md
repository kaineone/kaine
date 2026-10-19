## Why

The world model is a "latent recurrent model trained on the entity's waking trajectories" (§4 table, after Ha and Schmidhuber 2018 and Hafner et al. 2025), and its test is whether its prediction error "changes the sequence of accessed coalitions in characteristic ways" (§4). Its recurrent transition takes no action, so it cannot predict what the entity's own act or movement will do. A forward model of action outcomes is what turns a motor command into an expected consequence (Wolpert, Ghahramani, and Jordan 1995), and the DreamerV3 sequence model the module vendors conditions each step on the previous action (Hafner et al. 2025). This change designs action-conditioned prediction, so the world model can predict the outcome of an act on an effector and of a movement of the body.

Design only: not scheduled. Nothing is built until the start condition below holds.

### What already exists (audit, origin/main 6c8da178)

- An RSSM world model over workspace summaries, with a JAX core and a NumPy twin that read and write one checkpoint format (spec `world-model`; `kaine/modules/world_model/backend.py:25-38`, `rssm_numpy.py`).
- A waking prediction error, offline imagined scenarios in the sleep module's scenario window, and training over the waking buffer (`kaine/modules/world_model/module.py:10-26`).
- Learned weights persist by default, and a fork starts from its parent's world model (spec `world-model`, "Learned world-model weights persist by default", "A fork starts from its parent's world model").

### What is missing

- No action input. The GRU transition takes only the previous stochastic state and deterministic state (`kaine/modules/world_model/rssm_numpy.py:177-193`); `observe_step` and `imagine_step` take no action (`rssm_numpy.py:257-285`), and `RSSMConfig` has no action dimension (`rssm_numpy.py:47-59`). The module docstring states the scope: "It is NOT an agent: it has no actor, critic, reward, or return head" (`module.py:6-8`), which is right and separate from conditioning on actions.
- No action-outcome prediction. Imagined scenarios roll out from the prior trajectory alone (`module.py:17-24`), so nothing can ask what a candidate act would lead to.

## What Changes

A design, settled first in the paper and then in code.

1. Action-conditioned transition (paper §4, an appendix entry). Each step conditions on the entity's own previous action: the act intents realized by `act-intent-derivation` and `planning-act-proposals`, and the efference copy of the motor command from `embodiment-motor-contingency`. The module stays a world model with no actor, critic or reward head.
2. Continuity of a preserved entity. Recommended: the new action input enters with zero initial weights, so a world model loaded from a checkpoint without it predicts exactly as before until it learns, and a fork keeps its parent's model. The checkpoint format gains the action width in one step for both action kinds, so a preserved entity's weights migrate once.
3. Action-outcome error. Open for the paper change: whether the world model publishes the error between a predicted and an observed action outcome as its own report, the comparator signal of forward-model accounts.
4. Imagined acts. Open for the paper change: whether offline scenarios may roll out a candidate act, which would give the planning module and goal-directed grasping a predicted outcome to weigh.

## Dependencies and start condition

- Gate: The module-addition study has completed its first round (`module-ignition-study` task 2.5) and reached the §6.5 hardware stage. The world model joins in that first round (branch 2), so it is in the study by then.
- Dependencies: `act-intent-derivation` and `embodiment-motor-contingency` merged, so both action streams exist when the transition gains its action input. Conditioning on both at once changes the checkpoint format once.
- Start condition: Both hold. It may run in parallel with `active-vision`, which it does not need.

## Paper sections it depends on

§4 (the world-model row and paragraph), §6.5 (the study order), §10 (learning from experience), and the appendix entry the paper change adds for the transition.

## Evidence

| Study | Used for | Status |
| --- | --- | --- |
| Hafner, Pasukonis, Ba and Lillicrap (2025), *Nature* 640, 647-653 | the RSSM sequence model conditions on the previous action | verified (cited in the paper; the action-conditioned sequence model is in the method) |
| Ha and Schmidhuber (2018), arXiv:1803.10122 | a learned world model that predicts the next latent state from the current one and the action | verified (cited in the paper) |
| Wolpert, Ghahramani and Jordan (1995), *Science* 269, 1880-1882 | a forward model predicts the consequence of a motor command | verified (cited in the paper) |
| Hassabis and Maguire (2007) | scene construction, the brain function the row cites | verified (cited in the paper) |

## Capabilities

### New Capabilities

None until the paper change settles the design.

### Modified Capabilities

To be specified by the implementation change: `world-model` (the action-conditioned transition, the checkpoint format, imagined acts).

## Impact

None now. With no action stream the input is zero and the model predicts as today.
