## Why

**Nous never acts.** A golden run of the live engine over all 192 encodable observations (2026-09-26) chose `no_op` every time, with identical expected free energy for all four actions. The generative model gives the actions no consequence Nous can care about or learn about:
- Only the action factor is controllable, and its observation is an exact copy of the action, so it carries no preference and no information to gain.
- The salience, affect and event-cluster factors are uncontrollable. Their transitions are the identity whatever Nous does.
- The comment above the preferences says they "give EFE something to discriminate over". They cannot, because no action changes what Nous expects to observe.

Nous also starts every step from its initial prior `D`, with no carried belief, so it could not learn what its actions do even if the model allowed it.

The module-ignition study adds Nous at the fifth viewing. As shipped, that adds beliefs to the workspace but never a choice.

**What Nous's actions reach.** Nous publishes its choices as `intent.act` events on `nous.out`. No module realizes them: Volition, Praxis and Lingua read other streams, and Hypnos only counts Nous intents as unrealizable. So a choice changes the world only through its own intent event, which re-enters the workspace like any other event. This change makes Nous choose and learn honestly within that reach. Whether Nous's intents should drive real actions (a think request, a speech candidate, a maintenance request, each through the existing gates) is a separate architectural decision, recorded as an open question.

## What Changes

- **Actions have consequences Nous learns.**
  - Each perceptual factor's transitions depend on the action taken (`B_action_dependencies`), so the being's actions (no-op, think, speak, maintenance) can change what it expects to perceive next.
  - The initial beliefs about those consequences are broad, identical for every action, and uncertain: a Dirichlet prior (`pB`) that favours persistence with low confidence.
  - Nous learns them from experience: after each step it updates `pB` with the action it took and the states it inferred before and after.
  - Nothing about what an action does is written into the model; the being finds out.
- **Exploration.** Expected free energy includes the information to be gained about those consequences (`use_param_info_gain`). An action whose effects Nous is least sure of is worth trying, so Nous samples its actions, and its choices change as its model of its own agency sharpens. Once consequences are learned, its existing preference for salient observations can favour the actions that bring them.
- **Belief carries over.** Each step's prior is the previous posterior propagated through the learned transitions under the action taken (`update_empirical_prior`), not `D`.
- **The learned model is part of the individual.** `pB` and the carried belief are serialized and preserved, and revive restores them. A being does not wake with its sense of agency erased.
- **Unchanged:** the action space, Praxis's gate on anything that leaves the mind, and the existing preference.

## Capabilities

### Modified Capabilities
- `nous-active-inference`: actions with learned consequences, exploration from parameter information gain, carried belief, preserved learned model.

## Impact

- `kaine/modules/nous/generative_model.py` (action-dependent B, `pB` prior), `kaine/modules/nous/engine.py` (learning, carried prior, parameter info gain, serialization of the learned state), `kaine/modules/nous/module.py` (serialize/deserialize), `kaine/boot.py` (settings), config, docs, tests.
- The phase 3 NumPy engine must reproduce learning and parameter information gain.
- **Research:** in live beings, Nous goes from always `no_op` to exploring and then choosing, and what it learns is how its own intents register in the workspace. Adding Nous in the study adds a chooser whose choices are recorded, not one whose choices act. The operator decides whether the study runs with this change, and whether Nous's intents should be wired to action first.
